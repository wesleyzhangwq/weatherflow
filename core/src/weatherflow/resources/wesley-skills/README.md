# Wesley Skills

Personal agent skills for Codex and other AI coding agents.

This repository is intended to collect reusable skills that teach an agent a specific workflow, project convention, tool integration, or domain process.

## Repository Layout

```text
.
├── skills/
│   └── <skill-name>/
│       ├── SKILL.md
│       ├── agents/
│       │   └── openai.yaml
│       ├── scripts/
│       ├── references/
│       └── assets/
├── docs/
│   └── imports/
│       └── third-party-skills.md
├── licenses/
│   └── <source-repo>/
│       └── LICENSE
└── templates/
    └── basic-skill/
```

## Current Skills

This repo currently includes 127 skills covering:

- Engineering workflows: specs, planning, TDD, debugging, review, security, performance, shipping.
- Tool workflows: Playwright, pytest, Docker, GitHub Actions, API testing, MCP server building, PDF/Excel/SQL/Markdown tasks.
- Chinese content workflows: formatting, translation, URL-to-Markdown, diagrams.
- Product workflows: PRDs, roadmaps, prioritization, user stories, release notes, meeting summaries.
- Team and accessibility workflows: parallel work, screen reader checks, WCAG audits.
- OPC and startup founder workflows: customer discovery, sales, content, launch, pricing, unit economics, fundraising, support, churn, hiring, SOPs, and weekly execution.

See [docs/imports/third-party-skills.md](docs/imports/third-party-skills.md) for source repositories, commits, licenses, and imported skill list.
See [docs/skills-list.md](docs/skills-list.md) for the Chinese skill catalog, responsibility boundaries, and recommended enabled skill sets.
See [docs/compatibility/claude-code.md](docs/compatibility/claude-code.md) for Claude Code compatibility notes.

It also includes original skills:

- `zouzhe`: renders the wrap-up report of a completed multi-step task as an imperial memorial (奏折) for the user to review and reply to.
- `opc-operating-system`: builds a lightweight one-person company operating system.
- `opc-weekly-review`: converts weekly founder work into next-week priorities.
- `opc-customer-pipeline`: manages discovery, sales, follow-up, and conversion tracking.
- `opc-offer-sprint`: turns customer evidence into a sellable offer and test plan.
- `opc-automation-map`: prioritizes automations for a solo operator.

## Skill Rules

- Put each skill in `skills/<skill-name>/`.
- Use lowercase letters, digits, and hyphens for skill folder names.
- Every skill must include `SKILL.md`.
- Keep `SKILL.md` concise and procedural.
- Put large reusable details in `references/`.
- Put deterministic helpers in `scripts/`.
- Put output templates, images, or boilerplate in `assets/`.
- Avoid extra documentation files inside individual skill folders unless the agent needs them to perform the task.

## Create a New Skill

Copy the basic template:

```bash
cp -R templates/basic-skill skills/my-new-skill
```

Then edit:

- `skills/my-new-skill/SKILL.md`
- `skills/my-new-skill/agents/openai.yaml`

## SKILL.md Minimum Shape

```markdown
---
name: my-new-skill
description: Use when Codex needs to ...
---

# My New Skill

Follow this workflow:

1. ...
2. ...
3. ...
```

## Local Use

For local Codex use, copy or symlink skills from this repository into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
ln -s /Users/wesz_station/Projects/wesley-skills/skills/my-new-skill ~/.codex/skills/my-new-skill
```

Use a real skill name in place of `my-new-skill`.
