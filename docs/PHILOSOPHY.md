# WeatherFlow Philosophy

## Product Constitution

These nine rules govern every WeatherFlow product and architecture decision. When a
feature idea, review comment, or user request conflicts with them, WeatherFlow does
not build that feature.

1. **Identity** — WeatherFlow is a rhythm coach and daily cockpit for developers
   trapped in the "inefficient -> no review -> more inefficient" loop.
2. **Two modes** — WeatherFlow has exactly two use modes:
   - **Rhythm mirror:** daily state card plus hypothesis calibration. Low frequency,
     high weight, passively triggered.
   - **Daily cockpit:** chat for querying and planning Calendar and GitHub. High
     frequency, lightweight, user initiated.
   These modes feed each other. Neither is optional.
3. **First screen** — The user's sense of their own state is the whole product.
   The first screen is always the rhythm card. Schedule lookup requires scrolling
   or typing. That friction is intentional.
4. **Integration line** — Core integrations are only Calendar and GitHub. No other
   integrations are planned; this is a product stance, not a temporary gap.
5. **Promise** — WeatherFlow does not make you more efficient. It helps you see
   your rhythm clearly and pulls you back before burnout. Additive tools such as
   Reclaim or Motion fit more tasks in; WeatherFlow is subtractive and may suggest
   doing less.
6. **Philosophy** — WeatherFlow does not pretend to know you better than you know
   yourself. We assemble understanding together. Therefore hypotheses must have
   evidence, evidence must be traceable, and `profile.md` must remain readable and
   editable by the user.
7. **Passive stance** — WeatherFlow always waits for the user to come to it. It
   does not proactively push, notify, or interrupt. Scheduled checks may update
   evidence, but they do not generate hypotheses or disturb the user.
8. **Only chat creates write proposals** — Proposals are generated only in the
   Chat flow. Check-in and the home rhythm card never produce write-action
   suggestions.
9. **The card is the face** — The Hypothesis card is the core UI of the
   WeatherFlow home screen. It must both display the current rhythm hypothesis and
   let the user calibrate it.

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
