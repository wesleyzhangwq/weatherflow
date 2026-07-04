# Phase 3 — Skills 体系 + 经 MCP 分发（已完成）

## 交付

```
skills/
├── README.md                          # Skills×MCP 分工宣言（capability vs methodology）
├── weatherflow-weekly-review/SKILL.md # 周回顾方法论：证据纪律/输出结构/降级路径
├── weatherflow-rhythm-coach/SKILL.md  # 教练礼仪：升级阶梯/假设契约/HITL 写礼仪
└── weatherflow-mcp-integration/SKILL.md # 任意 host 挂载/env 契约/安全模型/按频率排序的故障手册
```

设计要点：
- **frontmatter description 即触发器**（何时加载写进 description——渐进披露的第一层）；
- 三个技能分别覆盖「任务方法论 / 产品人格与安全礼仪 / 运维接入」三类知识，互不重叠；
- 内容全部锚定真实实现（critic 的 source_event_id 契约、annotations 门禁、dry_run、
  env 不继承这个经典坑、Keel 作为参照消费者）——没有一条是泛泛的最佳实践。

## 杀手锏：skills over MCP

统一 server 新增：
- `weatherflow://skills` —— JSON 索引（name/description/uri，读 frontmatter 生成）
- `skill://weatherflow/{name}` —— 资源模板，按名取 SKILL.md 全文（含路径穿越防护）

意义：**没有文件系统访问权的远程 host 也能经协议拉取方法论**——把"Skills 分发"本身
做成了 MCP 的一个应用场景，两个主攻点在同一实现里咬合。

## 验证

196 tests 全绿（新增 skills-over-protocol 合同：索引含三技能、模板取回 frontmatter、
未知名/穿越名优雅降级）；ruff 干净。
