# WeatherFlow Overhaul 总报告

> 分支 `overhaul/mcp-skills` · 2026-07-03 · 授权：可无视既有产品哲学，终极目标 =
> 实用好用 + 被当前 AI 行业面试官欣赏，**主攻 MCP 与 Skills**。
> 全程记录：[00-audit](00-audit.md) → [01-plan](01-plan.md) → [02](02-phase1-unified-mcp.md) / [03](03-phase2-protocol-first-backend.md) / [04](04-phase3-skills.md)。

## 一、改了什么（四次提交，全部可回溯）

| Commit | 内容 |
|---|---|
| f22dca7 | Phase 0：审计（8 项"不美"清单，A1-A8）+ 执行蓝图 |
| dbf0867 | Phase 1：**统一 MCP server** —— 15 tools（全带 ToolAnnotations + 三态 meta）、5 resources、3 prompts、stdio+HTTP 双传输；聚合而非重写，旧入口零改动 |
| d7a9543 | Phase 2：**协议先行的 backend** —— `list_tools` 全 schema、`discover_from_mcp()` 启动发现注册表（手写表降为兜底）、actor 式长驻会话池（连接复用+透明重启）、lifespan 布线 |
| 8cdc465 | Phase 3：**Skills 体系** —— 3 个渐进披露 SKILL.md + 分工宣言，且经 `skill://weatherflow/{name}` 资源模板**从协议分发** |
| （本次） | Phase 4/5：README「Agent 原生接口」门面、ruff 遗留 8 错清零、本报告 |

## 二、为什么这么改（每条都能答"所以呢"）

1. **A1 schema 三重手工副本 → 协议即事实源**。原来 MCP server 签名、backend 手写注册表、外部消费方三处定义同一工具；现在 server 是唯一定义点，backend 启动时 `list_tools` 发现并重建注册表（三态从 `_meta.weatherflow.mode`/annotations 推导），发现失败静默回退静态表。副产物：LLM 工具面 10→13 自动扩容且策略不破。
2. **A2 工具袋 → 全协议表面**。tools 只是 MCP 的 1/5：加 resources（状态）、prompts（工作流）、annotations（安全语义）、instructions（server 级契约）、双传输。`create_or_update_file` 从"write"改标 `destructiveHint=true`——注解比三桶枚举更诚实，这类细节正是面试官区分"用过"与"理解"的地方。
3. **A3 每调用 spawn 子进程 → actor 会话池**。anyio 取消域是任务亲和的（stdio 传输的硬约束），所以不能做朴素连接池——每个 server 命令一个 owner task 串行服务队列。重复调用降到纯上游 API 延迟；传输死亡透明重启一次。
4. **A5 Skills 缺失 → 三技能 + 协议分发**。能力（MCP）与方法论（Skills）分层：周回顾的证据纪律、教练的升级阶梯与 HITL 礼仪、接入运维的故障手册（按真实频率排序）。`weatherflow://skills` 索引 + `skill://` 模板让无文件系统的 host 也能拉取——两个主攻点在同一实现咬合。
5. **刻意保留的"旧哲学"**（授权可拆但拆了自毁）：L1 append-only、FIV 派生记忆、interrupt HITL、destructive 不注册。它们不是包袱，是安全叙事的骨架——本次全部原样保留并在 annotations/skills 里显式化。

## 三、怎么验证的

- **196 tests 全绿**（backend 142 = 139+3 发现合同；mcp_servers 54 = 49+5 统一 server 合同），hermetic 纪律保持（发现在 conftest 关闭）；ruff 0 错误。
- **防漂移合同**：统一 server 与旧 server 的 inputSchema **逐字节一致**测试锁死（LLM 路由器训练所依赖的签名不会漂）。
- **真实冒烟**：stdio 全表面（15/5/3 + 真实 `github.list_repos`）；池化延迟实证；**跨仓库兼容**——Keel M6 的 executor 经旧入口实调 `github.get_repo_status` 成功返回。

## 四、面试叙事口径（30 秒版）

「我把 WeatherFlow 的 agent 接口层重造了一遍：一个统一 MCP server 暴露全协议表面——15 个带
annotations 的工具、5 个只读资源、3 个 prompt、双传输；backend 自己作为 MCP 客户端在启动时从
协议**发现**工具注册表，手写 schema 从此只是离线兜底；读路径走 actor 式长驻会话池，因为 stdio
传输的取消域是任务亲和的。方法论层用 Skills 承载，而且技能本身经 `skill://` 资源模板从协议分发。
安全模型三层：server 诚实自报 annotations，host 按三态门禁（写操作一律 HITL 提案），server 侧
还有写总闸和 dry_run 兜底。」

## 五、诚实的遗留项（设计已给、未执行）

| 项 | 原因与建议 |
|---|---|
| 前端可视化 MCP 面板（inspector 式） | 收益/成本比低于主攻项；建议后续在 dashboard 加一页调 `weatherflow://skills` 与工具列表展示 |
| prompts 单元测试 | 渲染已在冒烟覆盖，参数矩阵测试属锦上添花 |
| streamable HTTP 的鉴权 | 当前假定本机/可信网段；对外暴露需加 token 校验（FastMCP auth 钩子位已留） |
| 产品逻辑大改（T2 调度策略等） | 审计未发现"不美"级问题，动它属为改而改 |

## 六、给下一个会话的续跑锚

分支未合并、未推送。若继续：读本报告 + `git log overhaul/mcp-skills` 即可；
遗留项按上表优先级排。合并前建议：`pytest backend/tests mcp_servers/tests` + Keel 侧冒烟一遍。
