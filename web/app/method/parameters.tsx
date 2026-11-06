"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { getReport, getRepos, type Report, type RepoSummary } from "@/lib/api";

export default function Parameters({ repo }: { repo: string | null }) {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getRepos()
      .then(setRepos)
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    const [owner, name] = (repo ?? "").split("/");
    if (!owner || !name) return;
    getReport(owner, name)
      .then(setReport)
      .catch((e: Error) => setError(e.message));
  }, [repo]);

  const cell = "py-1.5 pr-4";
  return (
    <div className="space-y-4">
      {error && <p role="alert" className="font-medium">{error}</p>}
      <p className="text-small">
        {repos.map((r, i) => (
          <span key={r.canonical_slug}>
            {i > 0 && <span className="text-muted"> · </span>}
            <Link
              href={`/method?repo=${r.canonical_slug}`}
              aria-current={r.canonical_slug === report?.repo.canonical_slug ? "page" : undefined}
              className="font-mono hover:underline aria-[current=page]:font-semibold aria-[current=page]:text-ink"
            >
              {r.canonical_slug}
            </Link>
          </span>
        ))}
      </p>
      {report && (
        <table className="w-full border-collapse text-left text-small tabular-nums">
          <caption className="pb-2 text-left font-mono font-semibold">
            {report.repo.canonical_slug}
          </caption>
          <tbody>
            {Object.entries(report.method.parameters).map(([name, value]) => (
              <tr key={name} className="border-b border-line">
                <th scope="row" className={`${cell} font-mono font-normal text-muted`}>
                  {name}
                </th>
                <td className="py-1.5">{value}</td>
              </tr>
            ))}
            <tr className="border-b border-line">
              <th scope="row" className={`${cell} font-mono font-normal text-muted`}>
                area depths
              </th>
              <td className="py-1.5">
                {JSON.stringify(report.method.area_rule.depths)} (threshold share{" "}
                {report.method.area_rule.threshold_share}, max depth{" "}
                {report.method.area_rule.max_depth})
              </td>
            </tr>
            <tr className="border-b border-line">
              <th scope="row" className={`${cell} font-mono font-normal text-muted`}>
                excluded directories
              </th>
              <td className="py-1.5">{report.method.excluded_dirs.join(", ")}</td>
            </tr>
            <tr className="border-b border-line">
              <th scope="row" className={`${cell} font-mono font-normal text-muted`}>
                sweep commits excluded
              </th>
              <td className="py-1.5">{report.method.sweep_commits_excluded}</td>
            </tr>
          </tbody>
        </table>
      )}
    </div>
  );
}
