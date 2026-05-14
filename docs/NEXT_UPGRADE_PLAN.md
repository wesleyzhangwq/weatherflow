# Next.js Major Upgrade Plan

The frontend currently uses Next.js 14. A production dependency audit reports
Next.js advisories whose automated fix path moves to a newer major version. Do
not run `npm audit fix --force` blindly; treat this as a planned migration.

## Goal

Upgrade Next.js in a controlled branch while preserving the current app-router
dashboard behavior.

## Proposed Steps

1. Create a dedicated branch, for example `upgrade/next-major`.
2. Record the current baseline:
   - `make check`
   - `npm audit --omit=dev` from `frontend/`
3. Upgrade the frontend stack together:
   - `next`
   - `react`
   - `react-dom`
   - `eslint-config-next`
   - related `@types/*` packages if required
4. Read the official Next.js migration guide for every crossed major version.
5. Run and fix:
   - `cd frontend && npm run lint`
   - `cd frontend && npm run build`
   - `make check`
6. Manually verify:
   - dashboard SSR data loading
   - check-in client submission
   - reflection and timeline routes
   - Docker Compose frontend -> backend behavior
7. Re-run `npm audit --omit=dev` and document remaining advisories, if any.

## Risks To Watch

- App Router behavior changes.
- React major-version compatibility.
- ESLint config changes.
- Docker Compose dev server behavior.
- `NEXT_PUBLIC_API_BASE` / `NEXT_SERVER_API_BASE` differences between browser
  and server-side rendering.

## Acceptance Bar

The upgrade is acceptable only when `make check` passes and the main dashboard,
check-in, reflection, and timeline flows work locally.
