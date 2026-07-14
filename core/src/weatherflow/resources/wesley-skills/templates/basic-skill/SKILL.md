---
name: basic-skill
description: Use when Codex needs to perform a specific repeatable workflow. Replace this description with clear trigger conditions before using the skill.
---

# Basic Skill

Follow this workflow:

1. Confirm the user request matches the skill trigger.
2. Read only the referenced resources that are relevant to the current task.
3. Execute the workflow using the repository's existing conventions.
4. Verify the result with a concrete command, artifact inspection, or documented check.
5. Report the outcome, changed files, and any remaining limitations.

## Resources

- Use `scripts/` for deterministic helper scripts.
- Use `references/` for detailed documentation loaded only when needed.
- Use `assets/` for templates, images, or other output resources.
