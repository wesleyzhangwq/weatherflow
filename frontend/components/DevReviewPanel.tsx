"use client";

import { useState } from "react";
import { api, type DevReview, type DevReviewProviderReadiness } from "@/lib/api";

export function DevReviewPanel({
  initial,
  history,
  providers
}: {
  initial: DevReview | null;
  history: DevReview[];
  providers: DevReviewProviderReadiness[];
}) {
  const [review, setReview] = useState<DevReview | null>(initial);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const readinessKnown = providers.length > 0;
  const readyCount = providers.filter((item) => item.status === "ready").length;
  const canRun = !readinessKnown || readyCount > 0;

  async function runReview() {
    setRunning(true);
    setError(null);
    try {
      const next = await api.runDevReview(7);
      setReview(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dev review failed.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="card">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="text-xs uppercase tracking-widest muted">Dev Review</div>
          <h2 className="mt-2 font-serif text-2xl leading-tight">
            {review?.dev_weather || "Not run yet"}
          </h2>
          {review ? (
            <div className="mt-1 text-xs muted">
              Last run · <time dateTime={review.created_at}>{review.created_at}</time>
            </div>
          ) : null}
        </div>
        <button
          className="w-fit rounded-full bg-black px-4 py-2 text-sm text-white disabled:opacity-50 dark:bg-white dark:text-black"
          type="button"
          onClick={() => void runReview()}
          disabled={running || !canRun}
        >
          {running ? "Running..." : "Run"}
        </button>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {providers.length ? (
          providers.map((provider) => (
            <span
              key={provider.name}
              className="rounded-full border border-black/10 px-3 py-1 text-xs dark:border-white/10"
              title={provider.used_for}
            >
              {provider.label}:{" "}
              {provider.status === "ready" ? "Ready" : "Needs config"}
            </span>
          ))
        ) : (
          <span className="text-xs muted">Provider readiness unavailable.</span>
        )}
      </div>

      {error ? (
        <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : null}

      <p className="mt-4 text-sm leading-relaxed">
        {review?.summary ||
          (canRun
            ? "Run a dev review to turn recent work and calendar signals into one development rhythm snapshot."
            : "Configure GitHub or Google Calendar before running a Dev Review.")}
      </p>

      {!canRun ? (
        <p className="mt-2 text-xs muted">
          Set GITHUB_TOKEN or GOOGLE_CALENDAR_TOKEN_FILE in your environment.
        </p>
      ) : null}

      {review ? (
        <>
          <div className="mt-5">
            <div className="text-xs uppercase tracking-widest muted">Next Week</div>
            <p className="mt-2 text-sm leading-relaxed">
              {review.next_week_suggestion}
            </p>
          </div>

          <div className="mt-5 grid grid-cols-1 gap-5 md:grid-cols-2">
            <MiniList title="Work Threads" items={review.main_work_threads} />
            <MiniList title="Rhythm Risks" items={review.rhythm_risks} />
          </div>

          <details className="mt-5 text-sm">
            <summary className="cursor-pointer muted">Source coverage and run steps</summary>
            <div className="mt-3 space-y-4">
              <div>
                <div className="text-xs uppercase tracking-widest muted">
                  Source Coverage
                </div>
                {Object.keys(review.source_coverage).length ? (
                  <dl className="mt-2 space-y-1">
                    {Object.entries(review.source_coverage).map(([name, value]) => (
                      <div
                        key={name}
                        className="flex flex-col gap-0.5 border-t border-black/5 pt-2 dark:border-white/10 sm:flex-row sm:justify-between sm:gap-4"
                      >
                        <dt className="font-medium">{name}</dt>
                        <dd className="muted break-words sm:text-right">
                          {formatValue(value)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                ) : (
                  <p className="muted mt-2">No source coverage recorded.</p>
                )}
              </div>

              <div>
                <div className="text-xs uppercase tracking-widest muted">
                  Run Steps
                </div>
                {review.run.steps.length ? (
                  <ul className="mt-2 space-y-2">
                    {review.run.steps.map((step, index) => (
                      <li
                        key={`${step.name}-${index}`}
                        className="border-l-2 border-black/10 pl-3 dark:border-white/10"
                      >
                        <div className="flex flex-wrap items-baseline gap-x-2">
                          <span className="font-medium">{step.name}</span>
                          <span className="text-xs uppercase muted">
                            {step.status}
                          </span>
                        </div>
                        {step.summary ? (
                          <p className="muted mt-1 leading-relaxed">
                            {step.summary}
                          </p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted mt-2">No run steps recorded.</p>
                )}
              </div>
            </div>
          </details>
        </>
      ) : null}

      {history.length ? (
        <div className="mt-5 border-t border-black/5 pt-4 dark:border-white/10">
          <div className="text-xs uppercase tracking-widest muted">History</div>
          <ul className="mt-3 space-y-3 text-sm">
            {history.map((item) => (
              <li
                key={item.id}
                className="grid grid-cols-1 gap-1 sm:grid-cols-[minmax(0,1fr)_auto]"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <span className="font-medium">{item.dev_weather}</span>
                    <span className="text-xs uppercase muted">
                      {item.run.status}
                    </span>
                  </div>
                  <div className="mt-1 truncate text-xs muted">
                    {coverageSummary(item.source_coverage)}
                  </div>
                </div>
                <time
                  className="text-xs muted sm:text-right"
                  dateTime={item.created_at}
                >
                  {item.created_at}
                </time>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function MiniList({ title, items }: { title: string; items: string[] }) {
  const visibleItems = items.length ? items : ["None noted."];

  return (
    <div>
      <div className="text-xs uppercase tracking-widest muted">{title}</div>
      <ul className="mt-2 space-y-1 text-sm leading-relaxed">
        {visibleItems.map((item, index) => (
          <li key={`${item}-${index}`} className="break-words">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value) ?? "-";
}

function coverageSummary(coverage: Record<string, unknown>): string {
  const entries = Object.entries(coverage);
  if (!entries.length) return "no provider coverage";
  return entries
    .map(([name, value]) => {
      if (value && typeof value === "object" && "status" in value) {
        return `${name}: ${formatValue((value as { status?: unknown }).status)}`;
      }
      return `${name}: ${formatValue(value)}`;
    })
    .join(" · ");
}
