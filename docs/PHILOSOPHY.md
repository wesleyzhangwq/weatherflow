# WeatherFlow Philosophy

WeatherFlow is a developer rhythm companion.

It exists for the developer who can think deeply, collect information quickly,
and start many things, but still struggles to sustain a healthy action rhythm
over weeks.

## What It Is Not

WeatherFlow is not:

- a chatbot
- an AI girlfriend
- a general assistant
- a browser agent
- a task execution agent
- a productivity dashboard that tries to optimize everything

## What It Is

WeatherFlow helps a developer answer:

```text
What is my current work weather?
What is my development rhythm doing?
What should I gently protect or reduce next?
What has the system learned about how I work over time?
```

The product is intentionally narrow. It reads the user's own check-ins plus
GitHub and Calendar evidence. It does not watch the local filesystem or infer
too much from private raw activity.

## Weather

The State Agent maps the current state vector into one label:

```text
Momentum   - shipping, focused, things are moving
Recovery   - climbing back, rhythm returning
Confusion  - direction unclear, motivation flat
Overload   - too much coordination/input, too many open loops
Burnout    - drained, stress high, momentum collapsed
```

WeatherFlow does not try to eliminate bad weather. It helps the user notice it
early and move through it with less self-blame.

## Dev Review

Dev Review is central. It turns GitHub and Google Calendar into a weekly or
manual rhythm snapshot:

- main work threads
- shipping progress
- collaboration load
- meeting load
- rhythm risks
- one next-week suggestion

This is the evidence-backed side of WeatherFlow. The check-in gives subjective
state; Dev Review gives work-rhythm context.

## Memory

WeatherFlow's long-term memory is `profile.md`.

That file should stay small, readable, and editable. The goal is not to store
everything. The goal is for the user to feel:

> It remembers the parts that actually help me keep moving.

## Voice

Reflections and suggestions should be:

- short
- gentle
- non-preachy
- peer-like
- never a TODO flood
- never an HR review

WeatherFlow should sound like a wise, quiet collaborator, not a productivity
coach.
