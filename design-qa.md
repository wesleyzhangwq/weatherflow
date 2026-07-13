# WeatherFlow v3 Frontend Design QA

- Source visual truth:
  - `/Users/wesz_station/Desktop/截屏2026-07-12 18.11.37.png` (OpenHuman conversation)
  - `/Users/wesz_station/Desktop/截屏2026-07-12 18.09.35.png` (OpenHuman connections)
- Browser-rendered implementation:
  - `/Users/wesz_station/Projects/WeatherFlow/.codex/visual-qa/frontend-refresh/10-refined-chat.png`
  - `/Users/wesz_station/Projects/WeatherFlow/.codex/visual-qa/frontend-refresh/11-refined-tasks.png`
  - `/Users/wesz_station/Projects/WeatherFlow/.codex/visual-qa/frontend-refresh/12-refined-rhythm.png`
  - `/Users/wesz_station/Projects/WeatherFlow/.codex/visual-qa/frontend-refresh/13-refined-connections.png`
  - `/Users/wesz_station/Projects/WeatherFlow/.codex/visual-qa/frontend-refresh/14-refined-settings.png`
  - `/Users/wesz_station/Projects/WeatherFlow/.codex/visual-qa/frontend-refresh/15-responsive-chat-900x700.png`
- Side-by-side comparison evidence:
  - `/Users/wesz_station/Projects/WeatherFlow/.codex/visual-qa/frontend-refresh/compare-chat.png`
  - `/Users/wesz_station/Projects/WeatherFlow/.codex/visual-qa/frontend-refresh/compare-connections.png`
- Viewports: default 1280 × 720 and responsive 900 × 700
- Theme and states: dark mode; existing local Runs; unconfigured Composio project key; configured MiniMax-M3 model; empty approval and artifact context

## Full-view comparison evidence

The implementation follows the selected OpenHuman references without copying its
unsupported product taxonomy: persistent dark sidebar, blue outlined current item,
conversation as the dominant workspace, compact status rails, a persistent composer,
and restrained cards and borders. WeatherFlow adds two explicit header signals for
human weather and Agent task state because the v3 contract requires them to remain
separate. Connections intentionally exposes only GitHub, Gmail, and Google Calendar.

The source screenshots use a taller frame, so normalized comparisons judge content
regions and information hierarchy rather than pixel-for-pixel vertical density.

## Focused-region comparison evidence

The combined images keep the sidebar, conversation header, message column, composer,
Composio key strip, and connector card row legible at the same scale. No additional
crops were required. The task and rhythm views have no direct OpenHuman target and
were checked against WeatherFlow's architecture contracts and the shared visual
tokens instead.

## Required fidelity surfaces

- Fonts and typography: the system/PingFang stack is consistent across Chinese copy;
  headings use a compact 19–25 px scale, body text uses 11–14 px with readable line
  height, and long task text is clamped in navigation but fully readable in detail.
- Spacing and layout: sidebar, header, conversation column, task navigation, detail,
  context rail, composer, settings sections, and connector cards keep stable tracks.
  At 900 × 700 there is no document-level horizontal or vertical overflow.
- Colors and tokens: near-black surfaces, low-contrast borders, muted secondary copy,
  blue primary/focus states, green success, amber approval, and red review states are
  shared through WeatherFlow tokens.
- Image and icon fidelity: all visible UI icons use the existing Phosphor library.
  The source contains no required raster product art, and no placeholder imagery or
  handcrafted SVG assets were introduced.
- Copy and content: product copy is Chinese except provider names, model names, API
  terms, and dynamic model output. Known backend rhythm labels are translated for
  display without changing the stored domain value.
- Accessibility: navigation and task items expose stable accessible names and current
  state; keyboard focus is visible; segmented state controls expose pressed state;
  disabled composer and rhythm actions explain their prerequisites.

## Interaction and console checks

- Navigated through conversation, tasks, state weather, connections, and settings.
- Verified task selection, long-content containment, and readable event translation.
- Switched state input from active check-in to correction and verified the heading and
  pressed state update without writing a signal.
- Verified the empty, disabled, selected, and current-status states visible in the
  live daemon-backed UI.
- Verified 900 × 700 responsive navigation after fixing hidden-label accessibility.
- Browser console errors checked after navigation and interaction: none.

## Comparison history

### Baseline audit

- Evidence: `01-baseline-chat.png` through `05-baseline-settings.png`.
- [P1] Long task intents overran the task list and visually collided with the result
  and timeline columns.
- [P1] Conversation was visually sparse and did not show human weather and Agent task
  state as separate concepts near the primary interaction.
- [P2] The state-weather screen exposed too little of the backend policy, intensity,
  and validity data to explain how the product understood the user.
- [P2] Sending looked available when no Workspace was selected even though submission
  could not succeed.

### Refinement pass

- Fixed task layout with bounded navigation summaries, independent scrolling, a
  result card, translated timeline labels, event count, and dedicated context rail.
- Added separate accessible conversation chips for human weather and task state.
- Rebuilt the state page around real summary, policy, intensity, validity, check-in,
  and correction data from the Python snapshot.
- Disabled sending without a Workspace and exposed the reason beside the composer.
- Reworked hierarchy, sizing, tokens, focus states, and responsive layout across all
  five Cockpit sections.
- Post-fix evidence: `10-refined-chat.png` through `14-refined-settings.png`.

### Responsive pass

- [P1] At the collapsed-sidebar breakpoint, hidden navigation text also removed the
  buttons' accessible names, and the add-project label wrapped vertically.
- Added explicit navigation labels and restored the icon-only add-project treatment.
- Post-fix evidence: `15-responsive-chat-900x700.png`; document width and scroll width
  both equal 900 px, and document height and scroll height both equal 700 px.

## Follow-up polish

- P3: re-capture connected, syncing, connector-error, approval, artifact, and offline
  states after authentic accounts and representative Runs exist locally.
- P3: dynamic model output can later receive Markdown rendering once that renderer is
  added as an explicit product contract rather than a presentation-only shortcut.

## 2026-07-13 multi-provider model configuration pass

- Source visual truth:
  `/var/folders/4k/fygl6mrx1px2fq_5f83s_hq80000gn/T/codex-clipboard-76c0e06f-80a2-4098-8e38-01e87dacf9c5.png`
- Browser-rendered implementation:
  `/Users/wesz_station/Projects/WeatherFlow/.codex/visual-qa/model-providers/weatherflow-model-settings-pass2b.png`
- Focused provider-region evidence:
  `/Users/wesz_station/Projects/WeatherFlow/.codex/visual-qa/model-providers/weatherflow-model-settings-focus-pass2.png`
- Initial comparison evidence:
  `/Users/wesz_station/Projects/WeatherFlow/.codex/visual-qa/model-providers/weatherflow-model-settings-pass1b.png`
- Viewport: 1410 × 796, matching the source screenshot.
- State: dark Cockpit Settings, MiniMax provider selected, API key absent, fixed
  official endpoint visible, local development daemon online.

### Full-view and focused comparison

The full-view comparison preserves WeatherFlow's persistent product sidebar while
adopting the source's large dark provider surface, tinted rounded provider pills,
right-aligned key-presence switches, clear title band, and restrained borders. The
provider crop confirms that labels, toggles, key form, and selected state remain
legible. The smaller provider count and same-page key form are intentional product
differences: WeatherFlow supports seven bounded domestic providers rather than the
source's broad catalog, and configuration must remain directly actionable.

Required fidelity surfaces were rechecked: system/PingFang typography and hierarchy,
provider and form spacing, dark neutral plus provider-tinted color tokens, Phosphor
icons with no replacement raster assets, and Chinese product copy. The reference has
no required imagery, logo, or illustration inside the compared region.

### Comparison history

- [P2] Pass 1 provider controls and type hierarchy were too compact relative to the
  reference, making the provider surface read like a secondary utility panel.
- Fix: enlarged the Settings title band, provider heading, pills, type, padding, and
  toggles; introduced the lighter harness-style title background; retained the fixed
  WeatherFlow sidebar and in-context API-key panel.
- Post-fix evidence: `weatherflow-model-settings-pass2b.png` and
  `weatherflow-model-settings-focus-pass2.png`. No actionable P0/P1/P2 differences
  remain after accounting for the intentionally bounded provider set and inline
  configuration flow.

### Interaction and console checks

- Opened Settings from the persistent navigation.
- Switched the selected provider from MiniMax to DeepSeek and verified the provider
  name, official endpoint, placeholder, and submit label update together.
- Entered a non-secret test value and verified the configure action becomes enabled;
  cleared it without submitting or writing credentials.
- Browser console warnings and errors checked after interaction: none.

final result: passed
