---
name: opc-automation-map
description: Use when an OPC founder wants to identify, prioritize, and design automations for repeated work across lead capture, follow-up, content operations, customer onboarding, support, reporting, finance, and internal admin.
---

# OPC Automation Map

Map automation opportunities without automating the wrong work too early.

## Workflow

1. **Inventory repeated work**
   Ask for a week of recurring tasks across:
   - Lead sourcing and outreach
   - Follow-up and CRM updates
   - Content creation and repurposing
   - Customer onboarding
   - Support and FAQs
   - Reporting and metrics
   - Billing, invoices, and finance
   - File and knowledge management

2. **Score each workflow**
   Use 1 to 5 scores:
   - Frequency
   - Time cost
   - Error cost
   - Rule clarity
   - Revenue proximity
   - Tool readiness

3. **Choose automation type**
   - Checklist: keep manual but standardized.
   - Template: reduce rewriting.
   - No-code automation: connect tools with Zapier, Make, n8n, or native automations.
   - Script: deterministic local or cloud job.
   - Agent workflow: use only when judgment, summarization, or drafting is needed.

4. **Route supporting skills**
   - Use `automation-workflows` for Zapier/Make/n8n designs.
   - Use `sop-builder` or `process-docs` before automating unclear work.
   - Use `github-actions` for repository automation.
   - Use `mcp-server-builder` when an agent needs durable tool access.

5. **Output**
   Produce:
   - Automation backlog
   - Top three automations
   - Data flow for each
   - Failure modes
   - Manual fallback
   - Implementation order

## Guardrails

- Do not automate a workflow that changes every week.
- Automate closest to revenue or customer experience first.
- Always keep a manual fallback for business-critical automations.
