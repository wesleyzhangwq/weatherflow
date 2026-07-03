# Phase 2 — Backend 吃狗粮：协议即事实源 + 会话池（已完成）

## 问题（审计 A1/A3/A4）

- 工具 schema 三处手工副本（MCP server 签名 / backend 手写注册表 / 外部消费方），靠人肉同步；
- 客户端 `list_tools` 丢弃 inputSchema——手写注册表存在的根因；
- 每次读工具调用 spawn 一个新 MCP 子进程（uv+python 启动+握手），聊天内连续工具调用反复付冷启动税。

## 交付

| 文件 | 变化 |
|---|---|
| `app/mcp_client/pool.py`（新） | **actor 式长驻会话池**：每个 server 命令一个 owner task（anyio 取消域必须同任务进出——这是 stdio 传输的硬约束，也是不能用简单连接池的原因）；请求经队列+future 串行；传输级异常杀连接、下次调用透明重启一次；工具级 isError 不杀连接 |
| `app/mcp_client/client.py` | `list_tools` 返回完整 inputSchema + annotations + meta（协议发现的物质基础） |
| `app/mcp_client/tool_registry.py` | `discover_from_mcp()`：启动时从统一 server 构建注册表；三态取 `_meta.weatherflow.mode`（权威）或 annotations 推导（外部 server 通用）；**destructive 照旧拒注册**（不变量跨路径保持）；手写表降级为 offline fallback |
| `app/mcp_client/dispatcher.py` | 读路径改走 `pool_call`（新测试缝）；不再按 server 挑命令——统一入口 |
| `app/main.py` | lifespan 启动做发现（失败静默回退静态表，绝不阻塞启动）；退出关池 |
| `app/config.py` | `WF_MCP_UNIFIED_COMMAND` / `WF_MCP_DISCOVERY_ENABLED`（测试 conftest 置 false 保 hermetic） |

## 行为变化（有意的）

发现路径下 LLM 工具面 10 → **13**（新增 `calendar.update_event`、`github.update_issue`、`github.get_file`；两个 destructive 被过滤）——"server 扩了能力，backend 自动跟进且策略不破"正是协议先行的意义。

## 验证

- 195 tests 全绿（backend 142 = 139+3 新发现合同；mcp_servers 53 = 49+4）；ruff 0 错误（顺手清了 8 个遗留）。
- 真实池化实证：同进程连续两次 `github.list_repos`，第二次降到纯 GitHub API 延迟（传输开销 0）；冷启动税只付一次。
- 测试缝迁移：`monkeypatch(dispatcher.MCPToolClient)` → `monkeypatch(dispatcher.pool_call)`，写路径"绝不触网"断言保留。
