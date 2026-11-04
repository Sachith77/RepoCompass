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

  return (
    <div className="space-y-3">
      {error && <p className="text-red-700">{error}</p>}
      <p className="text-sm">
        {repos.map((r, i) => (
          <span key={r.canonical_slug}>
            {i > 0 && " · "}
            <Link href={`/method?repo=${r.canonical_slug}`} className="underline">
              {r.canonical_slug}
            </Link>
          </span>
        ))}
      </p>
      {report && (
        <div className="space-y-2 text-sm">
          <p className="font-semibold">{report.repo.canonical_slug}</p>
          <table className="border-collapse bg-white">
            <tbody>
              {Object.entries(report.method.parameters).map(([name, value]) => (
                <tr key={name} className="border-b border-neutral-100">
                  <td className="p-2 font-mono">{name}</td>
                  <td className="p-2">{value}</td>
                </tr>
              ))}
              <tr className="border-b border-neutral-100">
                <td className="p-2 font-mono">area depths</td>
                <td className="p-2">
                  {JSON.stringify(report.method.area_rule.depths)} (threshold share{" "}
                  {report.method.area_rule.threshold_share}, max depth{" "}
                  {report.method.area_rule.max_depth})
                </td>
              </tr>
              <tr className="border-b border-neutral-100">
                <td className="p-2 font-mono">excluded directories</td>
                <td className="p-2">{report.method.excluded_dirs.join(", ")}</td>
              </tr>
              <tr>
                <td className="p-2 font-mono">sweep commits excluded</td>
                <td className="p-2">{report.method.sweep_commits_excluded}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
