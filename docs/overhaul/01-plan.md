# Overhaul Phase 1-5 — 执行蓝图（2026-07-03）

> 断点续跑锚：每个 Phase 完成即提交（分支 `overhaul/mcp-skills`）并在本文件勾选。
> 额度中断后：读 00-audit + 本文件 + git log 即可无损续作。

## Phase 1 · 统一 MCP server（主攻）✅ 目标形态

新包 `mcp_servers/weatherflow/`（一个 server 替代两个工具袋，旧入口保留为薄 shim）：

```
mcp_servers/weatherflow/
├── server.py        # FastMCP("weatherflow")；--transport stdio|http
├── toolset.py       # 全部 10 工具：复用旧 tools.py 实现 + ToolAnnotations
├── resources.py     # weatherflow://profile · events/recent · rhythm/current · hypotheses/active
├── prompts.py       # weekly_review / plan_today / rhythm_checkin
└── __main__.py      # python -m mcp_servers.weatherflow
```

- annotations 映射三态：read→readOnlyHint=true；write→readOnlyHint=false, destructiveHint=false（+幂等按工具）；destructive 依旧不注册（叙事保留）。
- structured output：工具返回 dict → FastMCP 自动 structuredContent；关键工具加返回类型注解。
- 兼容 shim：`weatherflow_calendar/server.py`、`weatherflow_github/server.py` 改为从统一 toolset 组装出同名子集 server（Keel/backend 现有命令行为不变）。
- 验收：MCP 客户端脚本 list_tools（含 annotations）/list_resources/list_prompts/call_tool 全通；Keel M6 executor 冒烟不回归。

## Phase 2 · Backend 吃自己的狗粮（协议即事实源）

- `client.py`：list_tools 返回完整 inputSchema+annotations；新增 `MCPSessionPool`（每 server 一条长驻会话，懒建/断线重建）。
- `tool_registry.py`：新增 `discover_from_mcp()` —— 启动时从统一 server 发现工具，annotations→三态；手写表降级为 offline fallback（测试/无子进程环境）。
- `dispatcher.py`：走会话池，不再每调用 spawn。
- 验收：现有 139 测试全绿 + 新增发现/池化合同测试；实测连续两次工具调用第二次 <100ms。

## Phase 3 · Skills 体系（主攻）

```
skills/
├── README.md                        # Skills×MCP 分工的设计声明
├── weatherflow-weekly-review/SKILL.md   (+ scripts/collect.py)
├── weatherflow-rhythm-coach/SKILL.md
└── weatherflow-mcp-integration/SKILL.md
```

- SKILL.md 按渐进披露写：frontmatter(name/description 触发条件) → 快速路径 → 深度参考。
- 亮点：统一 server 把 skills 目录作为 MCP resources 暴露（`skill://weatherflow/<name>`）——任何 host 可经协议拉取方法论。
- 验收：Claude Code 本地加载技能可用；resources 读取返回 SKILL.md 原文。

## Phase 4 · 质量与门面

- ruff 8 errors 清零；新增测试覆盖统一 server 合同。
- README 重写：hero 一句话 + 架构图 + Quickstart + **MCP 全表面表格** + **Skills 章节** + Security&Safety（三态/HITL/append-only 前置）。
- CHANGELOG-overhaul 摘要进 docs/overhaul/。

## Phase 5 · 总报告

`docs/overhaul/REPORT.md`：改了什么/为什么/怎么验证/面试叙事口径/遗留项。

## 进度勾选

- [x] Phase 0 审计（00-audit.md）
- [x] Phase 1 统一 MCP server + shim + 冒烟（dbf0867）
- [x] Phase 2 发现式注册表 + 会话池（d7a9543）
- [x] Phase 3 Skills 三件套 + skill:// resources（8cdc465）
- [x] Phase 4 ruff 清零 / 196 tests / README 门面
- [x] Phase 5 REPORT.md
