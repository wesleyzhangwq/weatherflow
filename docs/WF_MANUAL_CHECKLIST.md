# WeatherFlow Manual Checklist

Run the demo without touching real local data:

```bash
uv run --package weatherflow-backend python -m app.tools.run_demo_checkins
```

The command prints the temporary `DATA_DIR`. Use that directory if you want to start the backend against the demo data.

## Dashboard

- The first screen clearly emphasizes weather and the next suggestion.
- The next suggestion is short, concrete, and actionable.
- The profile card reads like a long-term profile, not a raw log dump.
- Recent reflections show grounding sources without exposing prompt details.

## Hypotheses

- Sensor hypotheses are phrased as weak, confirmable signals.
- Each hypothesis can be rated: accurate, unsure, inaccurate.
- Accurate hypotheses can influence later state/profile.
- Unsure hypotheses are remembered but do not directly steer state.
- Inaccurate hypotheses do not steer state.

## Demo Health

- The demo report shows exactly 300 check-ins.
- Weather distribution includes multiple labels.
- `profile.md` exists in the temporary data directory.
- The report includes recent suggestions and profile excerpt.

## Code Comprehension

- A coder can read `docs/WF_SIMPLE_FLOW.md` and explain the data flow in 10 minutes.
- The main path does not require understanding vector search, timeline, semantic KV, or session buffers.
