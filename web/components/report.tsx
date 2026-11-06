"use client";

// Report sections other than the chart and the area cards. Text from the API (heading, band
// names, notes) is shown as returned; band names only get sentence case.

import { useState } from "react";

import { Prose } from "@/components/ui";
import type { AreaActivity, Person, Report } from "@/lib/api";
import { date, percent } from "@/lib/format";
import { summarise } from "@/lib/summary";

export function Lead({ report }: { report: Report }) {
  return (
    <p className="max-w-[680px] text-lead leading-relaxed text-ink">
      {summarise(report).map((sentence, i) => (
        <span key={i}>
          {i > 0 && " "}
          <Prose sentence={sentence} />
        </span>
      ))}
    </p>
  );
}

export function EmptyState({ report }: { report: Report }) {
  const w = report.where_to_start;
  return (
    <div className="max-w-[680px] border-y border-line py-6">
      <p className="font-serif text-heading">No area has enough data to compare yet</p>
      <p className="mt-2 text-muted">
        An area needs at least {report.method.parameters.min_sample} finished newcomer PRs before
        its merge rate can be compared with the repo average. The areas map below still shows where
        work happens.
      </p>
      {w.not_enough_data.length > 0 && <NotEnoughData report={report} />}
    </div>
  );
}

export function NotEnoughData({ report }: { report: Report }) {
  const w = report.where_to_start;
  return (
    <p className="mt-4 max-w-[680px] text-small text-muted">
      <span className="text-ink">Not enough data</span> (fewer than{" "}
      {report.method.parameters.min_sample} finished newcomer PRs):{" "}
      {w.not_enough_data.map((a, i) => (
        <span key={a.area}>
          {i > 0 && " · "}
          <span className="font-mono">{a.area}</span> {a.mature_newcomer_prs}
        </span>
      ))}
    </p>
  );
}

// activity marks stay neutral: green, grey and rust belong to the bands
const ACTIVITY: Record<string, string> = {
  active: "border-ink bg-ink",
  steady: "border-muted bg-muted",
  dormant: "border-muted bg-transparent",
};

const people = (list: Person[] | undefined) =>
  list && list.length > 0 ? list.map((p) => `${p.login} (${p.count})`).join(", ") : "–";

const SHOWN = 10;

export function AreasMap({ areas }: { areas: AreaActivity[] }) {
  const [all, setAll] = useState(false);
  const sorted = [...areas].sort(
    (a, b) => b.commits_12mo - a.commits_12mo || a.area.localeCompare(b.area),
  );
  const visible = all ? sorted : sorted.slice(0, SHOWN);
  const withPeople = areas.some((a) => a.top_contributors !== undefined);
  const th = "py-2 pr-4 text-small font-medium text-muted";
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left">
          <thead className="border-b border-ink/70">
            <tr>
              <th className={th}>Area</th>
              <th className={th}>Activity</th>
              <th className={`${th} text-right`}>Commits, 12 months</th>
              <th className={`${th} text-right`}>90 days</th>
              <th className={`${th} text-right`}>Commit authors</th>
              {withPeople && <th className={th}>Key contributors (merged PRs)</th>}
              {withPeople && <th className={th}>Key reviewers (reviews)</th>}
            </tr>
          </thead>
          <tbody>
            {visible.map((a) => (
              <tr key={a.area} className="border-b border-line align-top hover:bg-wash">
                <td className="py-2 pr-4 font-mono text-small whitespace-nowrap">{a.area}</td>
                <td className="py-2 pr-4 text-small whitespace-nowrap">
                  <span
                    aria-hidden
                    className={`mr-1.5 inline-block h-2 w-2 rounded-full border ${
                      ACTIVITY[a.activity_band] ?? ACTIVITY.dormant
                    }`}
                  />
                  {a.activity_band}
                </td>
                <td className="py-2 pr-4 text-right tabular-nums">{a.commits_12mo}</td>
                <td className="py-2 pr-4 text-right tabular-nums">{a.commits_90d}</td>
                <td className="py-2 pr-4 text-right tabular-nums">{a.commit_authors_12mo}</td>
                {withPeople && (
                  <td className="min-w-44 py-2 pr-4 text-small text-muted">
                    {people(a.top_contributors)}
                  </td>
                )}
                {withPeople && (
                  <td className="min-w-44 py-2 text-small text-muted">{people(a.top_reviewers)}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sorted.length > SHOWN && (
        <button onClick={() => setAll(!all)} className="text-small font-medium text-accent hover:underline">
          {all ? `Show the top ${SHOWN}` : `Show all ${sorted.length} areas`}
        </button>
      )}
    </div>
  );
}

export function DataAndSample({ report }: { report: Report }) {
  const s = report.sample;
  const rule = report.method.area_rule;
  const cell = "py-1.5 pr-4";
  return (
    <details className="border-y border-line py-4">
      <summary className="font-medium hover:text-accent">Data and sample</summary>
      <div className="mt-4 max-w-[760px] space-y-3 text-small">
        <p className="max-w-[680px]">{s.note}</p>
        <p className="max-w-[680px] text-muted">
          Window {date(s.window_start)} to {date(s.window_end)}: {s.total_prs} human PRs,{" "}
          {s.bot_or_non_user_prs_dropped} bot or non-user PRs dropped, {s.sampled_prs} kept.
          Formal-review coverage {percent(report.where_to_start.formal_review_coverage)}. Excluded
          directories: {report.method.excluded_dirs.join(", ") || "none"}. Area depths{" "}
          {JSON.stringify(rule.depths)} (one level elsewhere; threshold share {rule.threshold_share},
          max depth {rule.max_depth}).
        </p>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left tabular-nums">
            <thead className="border-b border-ink/70 text-muted">
              <tr>
                <th className={`${cell} font-medium`}>Month</th>
                <th className={`${cell} text-right font-medium`}>Human PRs</th>
                <th className={`${cell} text-right font-medium`}>Bot or non-user</th>
                <th className={`${cell} text-right font-medium`}>Kept</th>
                <th className={`${cell} font-medium`}>Kept from</th>
                <th className="py-1.5 font-medium">Kept to</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(s.per_month).map(([month, m]) => (
                <tr key={month} className="border-b border-line">
                  <td className={cell}>{month}</td>
                  <td className={`${cell} text-right`}>{m.total}</td>
                  <td className={`${cell} text-right`}>{m.bots}</td>
                  <td className={`${cell} text-right`}>{m.sampled}</td>
                  <td className={cell}>{date(m.first)}</td>
                  <td className="py-1.5">{date(m.last)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </details>
  );
}
