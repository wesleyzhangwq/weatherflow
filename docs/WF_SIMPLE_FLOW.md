# WeatherFlow Simple Flow

WeatherFlow v2 keeps one main loop:

```text
check-in + profile.md + rated/repeated hypotheses
  -> StateAgent
  -> ReflectionAgent
  -> PlanningAgent
  -> profile.md refresh
```

## Core Ideas

- Weather is the current state estimate.
- The next suggestion is the most important action output.
- `profile.md` is the long-term user model. It is readable and editable.
- Sensors are weak inputs. They create hypotheses, not conclusions.
- Hypotheses influence state/profile only when the user rates them as accurate or they repeat.

## Main Storage

- SQLite keeps check-ins, state snapshots, reflections, sensor rows, and sensor hypotheses.
- Markdown keeps the long-term profile at `DATA_DIR/memory/profile.md`.
- Old semantic, episodic, timeline, event, and vector stores may still exist for compatibility, but they are not part of the lightweight main path.

## Daily Loop

1. User submits a check-in.
2. `StateAgent` reads recent check-ins, `profile.md`, and active hypotheses.
3. `ReflectionAgent` writes a short reflection with grounding sources.
4. `PlanningAgent` writes one next-step suggestion.
5. `MemoryAgent` refreshes `profile.md` from recent check-ins, reflections, suggestion feedback, and hypothesis feedback.

## Sensor Loop

1. Git, notes, and workspace sensors write deterministic activity rows.
2. Rule-based builders create low-confidence hypotheses.
3. The user rates each hypothesis: accurate, unsure, or inaccurate.
4. Accurate and repeated hypotheses can influence state/profile.
5. Unsure and inaccurate ratings are preserved as context, but do not directly steer state.
