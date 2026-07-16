# WeatherFlow Desktop Usability Repair

- **Date:** 2026-07-16
- **Status:** Complete
- **Scope:** Conversation layout, theme parity, managed MCP health, live screen
  time, and development signing reuse

## Outcome

The Cockpit remains usable at normal laptop viewports, light theme applies to
every icon surface, every MCP card shown to the user is genuinely runnable,
screen time refreshes from real local activity, and waking an unchanged
development build does not request the macOS password again.

## Delivery

1. Replace the permanent 300 px conversation hero with compact conversation
   chrome and preserve the composer/reading area at short window heights.
2. Move icon containers, source links, tags, status marks, and neutral brand
   icons onto semantic theme colors.
3. Repair npm MCP launch by admitting its verified Node runtime read-only;
   provide bundled offline Time and read-only Git servers; omit unsafe network
   roadmap presets from the renderer catalog.
4. Refresh activity summaries while the status-weather view is open and verify
   persisted macOS opt-in creates real Raw Activity Vault intervals.
5. Cache one matching stable signed development runtime, sign again only after
   a Rust relink, and make startup credential-presence checks non-secret and
   non-interactive.

## Acceptance

- The conversation header never consumes more than the compact header row.
- Light theme contains no dark icon tiles or white-only neutral brand marks.
- Filesystem, Memory, Time, and Git presets can install and become healthy;
  advertised presets never render a disabled “暂不可用” action.
- Screen-time totals change after real heartbeat ingestion without remounting.
- A second unchanged `pnpm dev:app` launch reuses the signed runtime, skips
  `codesign --force`, and opens no SecurityAgent password window.
- Required narrow tests and the repository quality gates pass.

## Verification

- Side-by-side screenshot QA confirms the former 300 px conversation hero is
  now a compact 118 px header with the message history and composer visible.
- Light-theme screenshot QA confirms sidebar, MCP marks, source links, tags,
  status badges, and neutral icons use light semantic surfaces.
- Real Seatbelt smoke tests report Filesystem healthy with 14 tools, built-in
  Time healthy with 2 tools, and built-in read-only Git healthy with 7 tools.
- The local Raw Activity Vault recorded 30 macOS activity updates and 475.7
  seconds during live QA; the status-weather charts rendered those real values.
- Two unchanged launches produced `reusing stable signed runtime`, and a
  post-launch window audit found no SecurityAgent window.
