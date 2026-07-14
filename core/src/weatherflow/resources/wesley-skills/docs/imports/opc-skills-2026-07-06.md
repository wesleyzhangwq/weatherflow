# OPC Skills Expansion Import Detail

Imported on 2026-07-06.

This expansion adds founder/operator skills for OPCs, solo technical founders, bootstrappers, and small founding teams.

## Source Repositories

| Source | Commit | License | Notes |
| --- | --- | --- | --- |
| `mfwarren/entrepreneur-claude-skills` | `e5e8f4107f62913d7a1dd7a61237605112ca2d7c` | MIT | Imported all 25 skills. Upstream `MetaAds` was imported as `metaads` to match frontmatter name. |
| `shawnpang/startup-founder-skills` | `4ad31b43eef3ae3755cc57ec7e435dab4699ab44` | MIT | Imported 46 non-conflicting skills. Skipped `cold-outreach`, `competitive-analysis`, `market-research`, and `pitch-deck` because those names were already imported from mfwarren. |

## mfwarren Skills

- `automation-workflows`
- `cold-outreach`
- `competitive-analysis`
- `copywriting`
- `decision-frameworks`
- `delegation-framework`
- `email-campaigns`
- `financial-modeling`
- `founder-productivity`
- `fundraising`
- `hiring-playbook`
- `landing-pages`
- `market-research`
- `metaads`
- `objection-handling`
- `offer-creation`
- `paid-ads`
- `pitch-deck`
- `pricing-strategy`
- `product-market-fit`
- `seo-content`
- `social-media`
- `sop-builder`
- `team-building`
- `unit-economics`

## shawnpang Skills

- `accelerator-application`
- `architecture-design`
- `board-update`
- `churn-analysis`
- `cicd-setup`
- `code-review`
- `community-discovery`
- `competitor-monitoring`
- `content-strategy`
- `contract-review`
- `daily-product-digest`
- `data-room`
- `earned-media-outreach`
- `email-marketing`
- `employer-brand`
- `event-hosting`
- `feedback-synthesis`
- `founder-thought-leadership`
- `fundraising-email`
- `interview-kit`
- `investor-research`
- `job-description`
- `landing-page`
- `launch-strategy`
- `lead-scoring`
- `mvp-scoping`
- `onboarding-flow`
- `partnership-outreach`
- `prd-writing`
- `privacy-policy`
- `process-docs`
- `proposal-generation`
- `review-mining`
- `roadmap-planning`
- `sales-script`
- `security-review`
- `sentiment-monitoring`
- `seo-technical`
- `soc2-prep`
- `social-content`
- `sourcing-outreach`
- `startup-context`
- `support-docs`
- `tech-stack-eval`
- `terms-of-service`
- `user-research-synthesis`

## Self-Authored OPC Skills

- `opc-operating-system`
- `opc-weekly-review`
- `opc-customer-pipeline`
- `opc-offer-sprint`
- `opc-automation-map`

## Import Adjustments

- Excluded upstream `README.md` files inside skill directories.
- Preserved required `SKILL.md`, `examples/`, `references/`, `scripts/`, and other supporting resources.
- Moved unsupported frontmatter fields under `metadata`.
- Added generated `description` fields to imported mfwarren skills that only had trigger metadata.
