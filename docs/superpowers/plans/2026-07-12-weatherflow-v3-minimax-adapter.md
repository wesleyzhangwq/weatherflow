# WeatherFlow v3 MiniMax Model Adapter Plan

**Goal:** Replace packaged Echo-only execution with an explicitly configured MiniMax OpenAI-compatible adapter while keeping credentials local, tool authority frozen, and provider failures recoverable.

## Adapter contract

- [x] Convert `ModelRequest` messages, frozen `ToolSpec` schemas, and tool-result history into MiniMax Chat Completions requests.
- [x] Map canonical dotted WeatherFlow tool IDs to bounded provider-safe function names and reject unknown returned functions.
- [x] Convert final text, tool calls, delegation calls, and usage into provider-neutral `ModelTurn` values; strip reasoning-only `<think>` content.
- [x] Classify timeouts, rate limits, server failures, authentication failures, malformed responses, and multiple tool calls without leaking credentials.

## Configuration and credentials

- [x] Add versioned per-Workspace model configuration containing provider, model, base URL, and credential reference only.
- [x] Store MiniMax API keys in macOS Keychain; accept a hidden CLI prompt and never put the key in argv, environment, SQLite, events, checkpoints, or logs.
- [x] Add `weatherflow configure-minimax` and `weatherflow model-status`; configuration validates the key/model before activation.
- [x] Resolve the configured adapter during `RuntimeContainer.create`; retain Echo only as an explicit unconfigured smoke fallback.

## Desktop and release

- [x] Surface model configuration/health in the local status API and Cockpit without exposing secret material.
- [x] Rebuild the standalone sidecar and local ad-hoc `.app`/`.dmg` after all adapter tests and full gates pass.
- [x] Document first-time MiniMax configuration for both `api.minimaxi.com` and `api.minimax.io` accounts.

Implementation follows observed RED → code → focused tests → `make check` →
sidecar/release rebuild → atomic commits. No model response may bypass the
existing capability snapshot, Trust Plane, approval flow, or Worker bound.
