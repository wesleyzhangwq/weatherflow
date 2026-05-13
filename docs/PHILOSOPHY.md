# WeatherFlow Philosophy

## What this project is *not*

WeatherFlow is **not**:

- a ChatBot
- an AI girlfriend / companion in the romantic sense
- a general-purpose assistant
- AutoGPT / browser-driving agent
- an OpenClaw clone
- a "do-everything" AI

If you treat it as any of those, the design will not make sense.

## What this project *is*

A **long-term life-state and growth companionship system** — an external executive function
that helps a high-cognition, high-information, *low-action* user maintain their long-term
growth rhythm.

The goal is **not** to do tasks for the user. The goal is to help the user keep moving.

## The Real Problem

Modern people don't lack information. They have collapsed long-term growth order:

- High cognition, high goals, high information intake
- But: low sustained action
- Bookmark hoarding, plan-making, project switching
- Chronic anxiety, frequent burnout
- Inability to ship long-term

WeatherFlow's question is **not** *"how can the user be more efficient?"*
It is *"why can't the user become who they want to become over time?"*

## The Weather Metaphor

Life-state behaves like weather. It changes; it cannot be willed away.

The State Agent maps the user's life-state vector
(`focus / stress / burnout / momentum / confidence / motivation`) into exactly
one of five weather labels:

```
Momentum   - shipping, in flow, things are moving
Recovery   - climbing back, momentum returning
Confusion  - direction unclear, motivation flat
Overload   - too much input, too many open loops, project switching high
Burnout    - drained, stress high, momentum collapsed
```

WeatherFlow does **not** try to eliminate bad weather. It helps the user **understand and walk
through** their own weather.

## Difference from OpenClaw / Task Agents

| OpenClaw                 | WeatherFlow                          |
| ------------------------ | ------------------------------------ |
| Task execution agent     | Long-term growth-companion agent     |
| Tool use / MCP / browser | Memory / reflection / user modeling  |
| Workflow automation      | Behavior analysis & gentle guidance  |
| "Do it for me"           | "Help me keep walking"               |

## Engineering Principles

1. **Small but Deep** — few files, clear structure, restrained features.
2. **Local-first** — local first, SaaS later (or never).
3. **Memory-centric** — memory is more important than the LLM.
4. **Reflection-first** — reflection > tool use.
5. **Human-centric** — understand the human, don't automate everything.

## Voice

Reflections and suggestions must be:

- gentle
- non-preachy
- understanding
- never feel like a TODO app
- never feel like an HR review

When in doubt: speak the way a wise, patient friend would speak — not the way a productivity
coach would.

## Success Criterion (the only one that matters)

Success is **not** "the agent is smart." Success is when the user starts to think:

> *"It really does seem to understand me more and more."*
