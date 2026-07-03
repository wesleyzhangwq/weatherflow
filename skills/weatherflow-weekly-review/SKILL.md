---
name: weatherflow-weekly-review
description: Run an evidence-based weekly rhythm review over a developer's calendar and GitHub activity via the WeatherFlow MCP server. Use when the user asks for a weekly review, rhythm retrospective, "how was my week", or wants to plan next week from real activity data. Requires the weatherflow MCP server mounted.
---

# Weekly Rhythm Review

Produce a review the user can *act on*, where every claim traces to a real
event. You are auditing rhythm (energy/焦点 allocation over time), not
productivity-shaming.

## Fast path

1. **Snapshot first** — read `weatherflow://rhythm/current` (7-day event mix
   + latest check-in) and `weatherflow://hypotheses/active`. If hypotheses
   exist, treat them as claims to verify, not facts.
2. **Gather signals** for the review window:
   - `github.get_recent_commits` + `github.list_pull_requests` on the user's
     active repo (`github.list_repos` if unknown)
   - `calendar.search_events` for the same window
3. **Contrast plan vs. reality**: meeting hours vs. uninterrupted blocks vs.
   commit cadence. Late-night commit clusters and >3 consecutive meeting
   hours are the two highest-signal patterns.
4. **Write the review** (structure below), then — only if a concrete slot
   change would help — propose `calendar.create_focus_block`.

## Output structure

```
## 本周节奏
<2-3 sentences, each citing concrete events (commit sha / event title+time)>

## 证据
- <pattern>: <evidence refs>

## 建议（≤3 条）
1. <specific, schedulable, with rationale>
```

## Rules

- **Evidence discipline**: no claim without a citable event. "You seem
  overloaded" is banned; "3 nights of commits past 23:00 (a1b2c3d…)" is the
  form. This mirrors WeatherFlow's own critic contract (source_event_id).
- **Writes are proposals**: `create_focus_block` returns a confirmable
  proposal; never present it as done. Prefer `dry_run=true` first to show
  the chosen slot.
- **≤3 suggestions.** One adopted beats five ignored.

## Degradation

- No `GITHUB_TOKEN` → calendar + resources only; say which signal is missing.
- Empty `rhythm/current` (fresh install) → fall back to raw tool queries;
  recommend the user start daily check-ins.
- Calendar token expired (401) → GitHub-only review; flag it, don't guess.
