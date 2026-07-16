# WeatherFlow Warm-Neutral Theme Consolidation

- **Date:** 2026-07-16
- **Status:** Complete
- **Scope:** Cockpit light/dark palette, status weather, screen time,
  automations, model providers, OAuth, settings, and connector marks

## Outcome

WeatherFlow now uses one coherent visual language in both themes. The original
black/navy and cold-blue layers no longer control visible Cockpit states.
Terracotta, ochre, sage, and warm taupe provide distinct semantic roles without
breaking the warm paper direction.

## Delivery

1. Define one shared semantic token set for warm backgrounds, text, borders,
   primary interaction, observation, healthy state, warning, and danger.
2. Replace blue status-weather, activity, automation, provider, OAuth, and
   settings states with semantic theme colors.
3. Normalize model-provider pills and toggles so vendors do not create an
   unrelated row of black, green, blue, and purple controls.
4. Make OAuth connector icons inherit a small reviewed warm palette instead of
   rendering vendor blues.
5. Give the light theme equal-specificity semantic overrides so the archived
   cool-gray layer cannot reappear through CSS cascade order.

## Acceptance

- No `--wf-blue` token remains in the desktop stylesheet.
- Reviewed blue vendor hex values do not remain in Cockpit connector markup.
- Light and dark status-weather icons, dimension tracks, and screen-time charts
  use terracotta, ochre, sage, and taupe.
- Automation filters/search/empty states, model toggles/lists, OAuth filters,
  and theme cards contain no bright blue or neutral-black selected state.
- Theme selection remains persisted under `weatherflow.theme`.
- Desktop component tests, contract tests, production build, and repository
  quality gates pass.

## Visual verification

- Light screenshots cover status weather, screen time, recent behavior,
  automation empty state, model providers, OAuth, and settings.
- Dark screenshots cover status weather, automation, model providers, and
  settings.
- Final review confirms warm card surfaces, legible contrast, consistent state
  hierarchy, and no visible cold-blue remnants in the inspected states.
