"use client";

// Report sections other than the chart and the area cards. Text from the API (heading,
// band names, notes) is shown as returned; band names only get sentence case.

import { useState } from "react";

import type { AreaActivity, Person, Report } from "@/lib/api";
import { date, percent } from "@/lib/format";
import { summarise } from "@/lib/summary";

export function SummaryCard({ report }: { report: Report }) {
  return (
    <section className="rounded-2xl bg-neutral-900 p-6 text-neutral-50 shadow-sm">
      <p className="text-sm font-medium tracking-wide text-neutral-400 uppercase">Summary</p>
      <div className="mt-2 space-y-2 text-lg leading-relaxed">
        {summarise(report).map((sentence) => (
          <p key={sentence}>{sentence}</p>
        ))}
      </div>
    </section>
  );
}

export function EmptyState({ report }: { report: Report }) {
  const w = report.where_to_start;
  return (
    <div className="rounded-xl border border-dashed border-neutral-300 bg-white p-6 text-center">
      <p className="font-medium">No area has enough data yet</p>
      <p className="mt-1 text-sm text-neutral-600">
        An area needs at least {report.method.parameters.min_sample} mature newcomer PRs before it
        can be compared with the repo average.
      </p>
      {w.not_enough_data.length > 0 && (
        <p className="mt-3 text-sm text-neutral-500">
          {w.not_enough_data.map((a) => `${a.area} (${a.mature_newcomer_prs})`).join(" · ")}
        </p>
      )}
    </div>
  );
}

const ACTIVITY: Record<string, string> = {
  active: "bg-emerald-50 text-emerald-800 ring-emerald-600/20",
  steady: "bg-amber-50 text-amber-800 ring-amber-600/20",
  dormant: "bg-neutral-100 text-neutral-600 ring-neutral-500/20",
};

const people = (list: Person[] | undefined) =>
  list && list.length > 0 ? list.map((p) => `${p.login} (${p.count})`).join(", ") : "–";

const SHOWN = 10;

export function AreasMap({ areas }: { areas: AreaActivity[] }) {
  const [all, setAll] = useState(false);
  const sorted = [...areas].sort((a, b) => b.commits_12mo - a.commits_12mo || a.area.localeCompare(b.area));
  const visible = all ? sorted : sorted.slice(0, SHOWN);
  const withPeople = areas.some((a) => a.top_contributors !== undefined);
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-xl border border-neutral-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-neutral-50 text-xs text-neutral-500">
            <tr>
              <th className="px-3 py-2 font-medium">Area</th>
              <th className="px-3 py-2 font-medium">Activity</th>
              <th className="px-3 py-2 text-right font-medium">Commits, 12 months</th>
              <th className="px-3 py-2 text-right font-medium">90 days</th>
              <th className="px-3 py-2 text-right font-medium">Commit authors</th>
              {withPeople && <th className="px-3 py-2 font-medium">Key contributors (merged PRs)</th>}
              {withPeople && <th className="px-3 py-2 font-medium">Key reviewers (reviews)</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-100">
            {visible.map((a) => (
              <tr key={a.area}>
                <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">{a.area}</td>
                <td className="px-3 py-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${ACTIVITY[a.activity_band] ?? ACTIVITY.dormant}`}>
                    {a.activity_band}
                  </span>
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{a.commits_12mo}</td>
                <td className="px-3 py-2 text-right tabular-nums">{a.commits_90d}</td>
                <td className="px-3 py-2 text-right tabular-nums">{a.commit_authors_12mo}</td>
                {withPeople && (
                  <td className="min-w-48 px-3 py-2 text-neutral-600">{people(a.top_contributors)}</td>
                )}
                {withPeople && (
                  <td className="min-w-48 px-3 py-2 text-neutral-600">{people(a.top_reviewers)}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sorted.length > SHOWN && (
        <button onClick={() => setAll(!all)} className="text-sm font-medium text-blue-700 hover:underline">
          {all ? `Show the top ${SHOWN}` : `Show all ${sorted.length} areas`}
        </button>
      )}
    </div>
  );
}

export function DataAndSample({ report }: { report: Report }) {
  const s = report.sample;
  const rule = report.method.area_rule;
  return (
    <details className="rounded-xl border border-neutral-200 bg-white p-4">
      <summary className="cursor-pointer font-semibold select-none">Data and sample</summary>
      <div className="mt-3 space-y-3 text-sm">
        <p className={s.is_sampled ? "rounded-lg bg-amber-50 p-3 text-amber-900" : "text-neutral-700"}>
          {s.note}
        </p>
        <p className="text-neutral-600">
          Window {date(s.window_start)} to {date(s.window_end)}: {s.total_prs} human PRs,{" "}
          {s.bot_or_non_user_prs_dropped} bot or non-user PRs dropped, {s.sampled_prs} kept.
          Formal-review coverage {percent(report.where_to_start.formal_review_coverage)}.
        </p>
        <p className="text-neutral-600">
          Excluded directories: {report.method.excluded_dirs.join(", ") || "none"}. Area depths:{" "}
          {JSON.stringify(rule.depths)} (one level elsewhere; threshold share {rule.threshold_share},
          max depth {rule.max_depth}).
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-neutral-500">
              <tr>
                <th className="py-1 pr-3 font-medium">Month</th>
                <th className="py-1 pr-3 text-right font-medium">Human PRs</th>
                <th className="py-1 pr-3 text-right font-medium">Bot or non-user</th>
                <th className="py-1 pr-3 text-right font-medium">Kept</th>
                <th className="py-1 pr-3 font-medium">Kept from</th>
                <th className="py-1 font-medium">Kept to</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100 tabular-nums">
              {Object.entries(s.per_month).map(([month, m]) => (
                <tr key={month}>
                  <td className="py-1 pr-3">{month}</td>
                  <td className="py-1 pr-3 text-right">{m.total}</td>
                  <td className="py-1 pr-3 text-right">{m.bots}</td>
                  <td className="py-1 pr-3 text-right">{m.sampled}</td>
                  <td className="py-1 pr-3">{date(m.first)}</td>
                  <td className="py-1">{date(m.last)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </details>
  );
}
