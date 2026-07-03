# Phase 1 — 统一 MCP server（已完成，commit dbf0867）

## 交付

`mcp_servers/weatherflow/` — 一个 server 暴露完整协议表面：

| 维度 | 内容 |
|---|---|
| Tools ×15 | 聚合两个旧 server 的全部 wrapper（**签名单一定义点不动 → LLM 路由器零 schema 漂移**，有 drift-guard 测试锁死） |
| ToolAnnotations | 三态→hints 映射：read→readOnly；write→非破坏；delete_event/create_or_update_file→destructiveHint=true（后者旧分类叫 write，注解比三桶枚举更诚实——覆写 blob 就是破坏性） |
| `_meta.weatherflow.mode` | 原三态桶随协议下发，客户端可无损重建策略 |
| Resources ×4 | `weatherflow://profile`（L3）/ `events/recent`（L1 尾）/ `rhythm/current` / `hypotheses/active`；sqlite 只读 URI 模式，store 缺失时返回 `{"available": false}` 而非异常 |
| Prompts ×3 | weekly_review / plan_today / rhythm_checkin——参数化工作流，指名要用的工具与资源 |
| 双传输 | stdio（默认）+ `--transport http`（streamable HTTP，:8765） |
| Server instructions | 含安全契约声明（annotations 语义 + 写门禁 + dry_run） |

## 设计决策

- **聚合而非重写**：旧 server 的 typed wrapper 仍是唯一签名定义点；统一层只加协议元数据。旧入口（Keel M6 与 backend 在用）零改动。
- delete/overwrite 类工具在 server 侧**照常暴露**但带诚实 annotations——"由 host 依 hints 自行做门禁"是 MCP 的正确分层；本项目 backend 的三态注册表就是这样一个 host 策略。

## 验证

- stdio 全表面冒烟：15 tools（8 readOnly / 2 destructive hints）、4 resources（读到真实 L1 checkin）、3 prompts 渲染、真实 `github.list_repos` 调用成功。
- 新合同测试 ×4（`mcp_servers/tests/test_unified_server.py`）：表面计数、注解↔三态一致性、**与旧 server 的 inputSchema 逐字节一致**（防漂移）、资源优雅降级。
