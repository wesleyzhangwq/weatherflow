# WeatherFlow v2.1 — 自主收尾轮验收说明

> 执行时间：2026-06-10 · 分支 `v2` · 4 个 commit
> 验证基线：**103 个测试全绿（2.6s）· ruff 全绿 · 前端 lint+build 全绿 · 真实 LLM 全链路浏览器级自验通过**

---

## 一、这轮发现并修复的核心 bug（按严重度）

| # | Bug | 用户可见症状 | 修复 |
|---|---|---|---|
| 1 | **Chat 页 SSE 从未真正工作**：sse-starlette 用 `\r\n\r\n` 分帧，前端按 `\n\n` 切分，缓冲永不flush | 发消息后页面毫无反应，直到刷新才能（靠 REST 历史）看到回答 | `chat/page.tsx` 分帧正则兼容 CRLF |
| 2 | **助手回答从不落 L1**（仅 resume 路径落） | 刷新后所有 AI 回答消失；`/history` 只有用户消息 | `routers/chat.py` 流结束后持久化 assistant chat_turn |
| 3 | **多轮对话失忆**：图的 messages 每轮只含 [system, 当前消息]，bundle 召回也不含 chat_turn | 问「我刚才说了什么」答「没找到记录」 | 路由从 L1 加载最近 12 轮注入 messages（实测：跨轮记住「周五下午不排会议」） |
| 4 | **本机代理 MITM 国内 API 域名** → 间歇性 `CERTIFICATE_VERIFY_FAILED` | hypothesis 生成/定时检查随机失败 | 新增 `NO_PROXY_HOSTS` 配置（.env 已配好 MiniMax/SiliconFlow 直连） |
| 5 | docker-compose qdrant healthcheck 用了镜像里不存在的 curl | `docker compose up` 全栈模式 backend 永远等不到依赖就绪 | 改为 bash /dev/tcp 端口探测 |
| 6 | mem0 PostHog 遥测被代理拦截后重试风暴 | 日志被 ERROR 刷屏 | 默认 `MEM0_TELEMETRY=False`（本地优先产品不外发遥测） |
| 7 | Langfuse 收到流式响应的空 usage 即抛错 | 每次流式调用一条 ERROR 日志 | usage 为空时传 None |
| 8 | rhythm 图 verify 失败无重试上限 | 最坏情况按递归上限烧 LLM 调用 | 重试封顶 1 次 |
| 9 | 测试套件不隔离（读真实 .env keys/真实 Qdrant/走系统代理） | 测试 110s、互相污染、可能写真实向量库 | conftest 全面隔离（**110s → 2.6s**） |
| 10 | dashboard `next_check_at` 把本地时间标成 UTC | 非 UTC 时区显示错误的绝对时间 | astimezone 修正 |

## 二、产品 80→90 的改进

1. **Token 级流式输出**：act 节点经 LangGraph custom stream channel 推 `answer_delta`，前端渐进渲染（带光标的「回答中…」气泡，final 到达原位替换）。`<think>` 块有专门的流式过滤器，不会闪现思考内容。配合 plan 节点关闭 thinking（省 ~10s），chat p50 从 45s → 29s，且首 token 后全程可见。
2. **语义记忆可视化**：新增 `memories_recalled` SSE 事件，chat 里以「🧠 想起了 N 段过往」芯片呈现 L2.5 召回结果——实测它召回「我习惯早上写代码、下午容易分心」的偏好后，建议里直接说「下午你容易分心，挑 30 分钟能收尾的小事」。
3. **Evidence 溯源弹层**：替换 `alert()` 占位——hypothesis 卡的「溯源」按钮与记忆芯片点击，统一打开 L1 事件详情 modal（类型/时间/payload/refs，Esc 关闭）。「evidence 必须可溯源」的哲学第一次有了像样的 UI 落点。
4. **Proposal 确认后自动续上**：确认执行 → 后端 resume 图 → 前端自动刷新历史，Agent 基于执行结果的后续回答当场出现（原来要手动刷新才看得到）。
5. mem0 Memory 进程级缓存 + search 放线程池（不再每次召回重建客户端、不再阻塞事件循环）。

## 三、环境与配置（已全部配好）

- `.env` 新增：`NO_PROXY_HOSTS=api.minimaxi.com,api.siliconflow.cn`、`MEM0_TELEMETRY=False`
- 依赖：`uv sync --all-packages --all-extras` 已执行（langgraph/mem0/langfuse 真实生效，非降级）
- 容器：Qdrant + Langfuse + langfuse-db 在跑（`docker compose up -d qdrant langfuse`）
- `/api/meta/status`：qdrant healthy ✓ · semantic_memory enabled ✓ · langfuse configured ✓ · scheduler running ✓

## 四、验收步骤（前后端跑起来后建议按此走）

```bash
# 后端（当前已在跑：127.0.0.1:8765）
make dev-backend
# 前端（127.0.0.1:3000）
make dev-frontend
```

1. **主页**：数据条（会议/提交/定时检查/待确认）+ 当前节奏 widget + 卡片堆；点任意 evidence 的「溯源」→ L1 事件弹层。
2. **Chat 多轮记忆**：发「记住一件事：我周五下午永远不排会议」→ 收到确认后再问「我刚才说什么时候不排会议？」→ 应直接答「周五下午」。
3. **流式**：任意提问，观察「回答中…」气泡逐段增长、完成后原位变成「最终回答」。
4. **记忆芯片**：问「结合你记得的我的偏好给条建议」→ 出现「🧠 想起了 N 段过往」→ 点芯片看原始事件。
5. **刷新页面**：完整对话历史（含 AI 回答）原样回来。
6. **Proposal（可选，会写真实 Google 日历）**：让它「帮我明天上午排一个 2 小时深度工作块」→ 出 Proposal 卡 → 拒绝（无副作用）或确认（真实创建日历事件 + Agent 自动续答）。
7. **可观测**：http://127.0.0.1:3001 Langfuse 里看 chat_run trace 树（节点=span，LLM 调用=generation）；`/api/meta/metrics` 看 P50/P95。

## 五、已知边界（如实声明）

- chat p50 仍 ~29s（MiniMax-M3 推理模型单次调用 ~10s × plan/act 串行）。流式让体验可接受；要进一步压只能换非推理模型或砍 plan 节点，这是产品权衡不是 bug。
- 评测体系（eval/）仍处于「已拆除待重建」状态（README 如实标注，ADR-005 待写）——这是 v2 roadmap 遗留项，不在本轮范围。
- 桌面宠物（desktop/）本轮未触碰（npm 依赖未装）。
- 测试时长说明：本机有系统代理时，老版本测试会泄漏网络调用；现已彻底离网，任何机器上都应 <5s。
