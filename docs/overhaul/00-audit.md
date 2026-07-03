# Overhaul Phase 0 — 全面审计（2026-07-03）

> 本轮改造的授权范围：可无视既有产品哲学/架构文档，终极目标 = 实用好用 + 让当前 AI 行业面试官欣赏，
> **主攻 MCP 与 Skills 设计**。基线：main @ b82e0b1，139 tests pass / 1.86s，ruff 8 errors。
> 硬约束（自设）：`mcp_servers.weatherflow_calendar.server` 与 `weatherflow_github.server` 两个
> stdio 入口必须保持可用——Keel M6 的 executor 和本仓 backend 配置都指向它们。

## 判定：保什么、拆什么

**保留并强化（这些恰恰是面试官欣赏的资产，拆了是自毁）**：
L1 append-only 事件溯源、FIV 分层记忆、interrupt+checkpointer 真 HITL、工具三态（destructive 不注册）、
hermetic 测试纪律、Langfuse/OTel 可观测。

**拆除/重造（真正"不美"的部分）**：见下表。

## 不美清单

| # | 问题 | 证据 | 严重度 |
|---|---|---|---|
| A1 | **工具 schema 三重手工副本**：MCP server 的 `@mcp.tool` 签名、backend `tool_registry.py` 手写 JSON schema、Keel `tools_all.json`——同一工具三处定义，靠人肉同步 | `tool_registry.py` 全文 232 行手写 schema | 🔴 架构级。面试官一问"漂移了怎么办"即溃 |
| A2 | **MCP server 只是"工具袋"**：仅 tools。无 resources（profile.md / rhythm 态 / L1 尾天然适合）、无 prompts（weekly review 天然适合）、无 tool annotations（readOnlyHint 与三态注册表是天作之合）、无显式 output schema、仅 stdio 单传输 | `weatherflow_calendar/server.py` 132 行全是 `@mcp.tool` | 🔴 主攻区。用了协议 1/5 的表面积 |
| A3 | **每次工具调用 spawn 一个新子进程**：`dispatcher._dispatch_read` 每次 `MCPToolClient(...)` + 新 session——每调用付出 Python 启动 + 握手（实测 ~1-2s） | `dispatcher.py:80-87`、`client.py:89-101` | 🟠 性能。聊天内连续 3 个工具 = 3 次冷启动 |
| A4 | **客户端丢弃协议的发现能力**：`client.list_tools()` 只取 name/description，扔掉 inputSchema——这正是 A1 手工注册表存在的根因 | `client.py:103-108` | 🔴 与 A1 同根 |
| A5 | **Skills 缺失**：当前 Agent 生态（Claude Code / Agent Skills）以 SKILL.md 渐进披露为能力打包标准，本项目为零 | 无 `skills/` 目录 | 🔴 主攻区 |
| A6 | 两个 server 样板重复：FastMCP 初始化、写门禁 `WF_MCP_WRITE_TOOLS_ENABLED` 模式各写一遍；`shared/` 近空壳 | 两个 server.py 292 行 vs 实际差异只有工具表 | 🟡 |
| A7 | ruff 8 errors（5 可自动修） | `ruff check` 基线 | 🟡 |
| A8 | 内部只读洞察（rhythm/hypotheses/profile）只有私有 REST API，外部 agent 生态无标准取用途径 | routers/ 仅 FastAPI | 🟠 与 A2 合并解决 |

## 面试官视角的机会点（2026 年中）

1. **MCP 全表面**：tools+resources+prompts+annotations+structured output+双传输，一个 server 秀完协议宽度；
2. **"MCP 即单一事实源"**：backend 经协议发现工具而非手工注册——把 A1/A4 变成叙事亮点；
3. **Skills×MCP 互补叙事**：MCP=能力接入，Skills=方法论知识（渐进披露），一个项目同时示范两者及其分工；
4. **连接池化的 MCP 客户端**：长驻会话 + 懒重连，能讲"stdio 子进程生命周期管理"；
5. 保留级资产（HITL/三态/事件溯源）在 README 里前置成 Security & Safety 章节。
