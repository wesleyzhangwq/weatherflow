# WeatherFlow Skills

Agent skills for working with WeatherFlow — packaged methodology that any
skills-capable host (Claude Code, or anything that can read a SKILL.md) can
load on demand.

## Why both MCP *and* skills

They answer different questions and compose:

| Layer | Question it answers | Shape |
|---|---|---|
| **MCP tools/resources** | *What can be done?* (capability) | Typed calls with annotations; read-only state |
| **MCP prompts** | *What's the short operational recipe?* | Parameterized one-shot instructions |
| **Skills** | *How is it done well?* (methodology) | Progressive-disclosure documents: trigger → fast path → deep reference |

A prompt fits in a paragraph; a skill carries judgment — evidence
discipline, degradation paths, escalation etiquette — that would bloat every
context if inlined. Hosts load a skill only when its trigger matches, which
is the whole point of progressive disclosure.

## Distribution: filesystem or over MCP

Skills live here as plain directories, and the unified MCP server also
serves them as resources, so remote hosts need no filesystem access:

- `weatherflow://skills` — JSON index of available skills
- `skill://weatherflow/{name}` — the SKILL.md body

## Catalog

| Skill | Trigger |
|---|---|
| `weatherflow-weekly-review` | User asks for a weekly review / rhythm retrospective |
| `weatherflow-rhythm-coach` | Interpreting rhythm data, writing hypotheses, coaching etiquette |
| `weatherflow-mcp-integration` | Mounting/debugging the WeatherFlow MCP server in any host |
