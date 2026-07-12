# WeatherFlow conversation-first desktop design QA

- Source visual truth: `/Users/wesz_station/Desktop/截屏2026-07-12 18.11.37.png`
- Supporting source visuals: `/Users/wesz_station/Desktop/截屏2026-07-12 18.09.35.png`, `/Users/wesz_station/Desktop/截屏2026-07-12 18.10.12.png`
- Implementation screenshot: `/Users/wesz_station/Projects/WeatherFlow/.codex/visual-qa/cockpit-pass2.png`
- Normalized implementation crop: `/Users/wesz_station/Projects/WeatherFlow/.codex/visual-qa/cockpit-pass2-crop.png`
- Combined comparison evidence: `/Users/wesz_station/Projects/WeatherFlow/.codex/visual-qa/conversation-comparison.png`
- Viewport: macOS 2940×1912 capture; Cockpit content rendered at 1080×760 CSS pixels
- State: dark theme, conversation view, populated local Run history, no pending approval or artifact

## Findings

No actionable P0, P1, or P2 visual differences remain for the approved design direction.

- Typography: both use a compact macOS system sans hierarchy. WeatherFlow uses PingFang SC in its fallback chain and maintains readable weights and line height for Chinese navigation, header, messages, and small metadata.
- Spacing and layout: the persistent left rail, dominant scrollable conversation, bottom composer, and secondary context rail preserve the reference hierarchy without clipping. The right rail is an intentional WeatherFlow addition for approvals and artifacts.
- Colors and tokens: near-black surfaces, low-contrast dividers, blue selection/message accents, and semantic green/amber/red status colors match the reference's restrained dark palette.
- Image and icon quality: the desktop uses the existing raster app asset for the Companion and a single Phosphor icon family for interface controls. No placeholder logos, emoji, handcrafted SVGs, or text-glyph service marks remain.
- Copy and content: all static product navigation and primary controls are Chinese. Dynamic historical Run content remains in its original user/model language by design.
- Responsiveness: the 1080×760 native viewport remains usable; the CSS breakpoint collapses the rail labels and contextual column below 980px without hiding the composer.
- Accessibility: controls have semantic labels, Escape cancels Capsule input, the Companion has a native drag region, reduced-motion is honored, and status is not communicated by color alone.

## Focused region comparison

The combined image compares the full left navigation, conversation body, and bottom composer at readable scale. A second crop was unnecessary because all fidelity-critical controls and typography are legible in that comparison.

## Comparison history

### Companion and Capsule simplification

- Companion contract: the ambient surface is now a 72×72 transparent native window containing one 56px weather button and a 44px Phosphor weather symbol. Mascot art, orbital rings, particles, speech UI, and decorative containers are absent.
- State separation: human weather remains the only primary visual; agent state is limited to one optional 11px status dot, and sensor degradation to one optional 7px dot.
- Drag behavior: a primary-button movement of at least 5px calls Tauri's native `startDragging()` API. The originating click is suppressed, while a stationary click still opens Capsule.
- Capsule contract: the native surface is 460×58 and contains only a 48px input capsule plus its close control. Submit, Escape, close, frontend blur, and native `Focused(false)` all dismiss it.
- Verification evidence: React interaction tests cover click-versus-drag and browser blur. Rust tests cover the native dimensions; the desktop contract test checks the focus-loss handler, Tauri drag permission, and adapter call.

### Pass 1

- Evidence: `/Users/wesz_station/Projects/WeatherFlow/.codex/visual-qa/cockpit-pass1.png`
- [P1] The always-on-top Companion remained over the Cockpit and obscured the conversation header.
- Fix: opening Cockpit now hides Companion; destroying Cockpit restores Companion. A Rust contract covers this lifecycle.
- Additional runtime issue found: a denied Keychain status lookup returned HTTP 500 and prevented Cockpit data refresh.
- Fix: model status now fails closed as `credential_available=false` without exposing Keychain details; a model-service regression test covers the denied lookup.

### Pass 2

- Evidence: `/Users/wesz_station/Projects/WeatherFlow/.codex/visual-qa/cockpit-pass2.png`
- Post-fix result: the Companion no longer overlays the conversation; Run history loads; the conversation header, messages, context, and composer are visible without overlap or clipping.
- Console/runtime check: the clean launch returned HTTP 200 for workspace, snapshot, Run, approval, artifact, timeline, and system-status reads. No frontend build or runtime exception appeared in the final capture.

## Primary interactions verified

- Companion click opens the explicit Cockpit; opening Cockpit suppresses the floating Companion.
- Capsule has an explicit close control and Escape cancellation.
- Conversation submission, navigation, approval, reset confirmation, provider selection, editable API Endpoint, and model save payload are covered by desktop interaction tests.
- Connection view contains only GitHub, Gmail, and Google Calendar and truthfully reports that OAuth client configuration is still required.

## Follow-up polish

- [P3] A future version can make the current-context rail collapsible to give long technical conversations even more horizontal room.

final result: passed
