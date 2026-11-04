"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { analyze, ApiError, getRepos, type RepoSummary } from "@/lib/api";
import { date } from "@/lib/format";

// The reference repositories from docs/BRIEF.md, by size.
const EXAMPLES = [
  { slug: "Kludex/starlette", size: "Small", note: "reached as encode/starlette" },
  { slug: "optuna/optuna", size: "Medium", note: null },
  { slug: "kubernetes/kubernetes", size: "Huge", note: null },
];

const GETS = [
  ["Where to start", "Areas where newcomer PRs were merged more or less often than the repo average, with sample sizes and intervals."],
  ["How it answers", "How long a first review usually takes, and how often newcomer PRs got no response at all."],
  ["Who is active", "Commit activity per area, and the people whose PRs were merged there and who reviewed PRs there (counts only)."],
];

export default function Home() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [repos, setRepos] = useState<RepoSummary[] | null>(null);
  const [reposError, setReposError] = useState<string | null>(null);

  useEffect(() => {
    getRepos()
      .then(setRepos)
      .catch((e: Error) => setReposError(e.message));
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await analyze(url);
      if (result.status === "cached") router.push(`/r/${result.report.repo.canonical_slug}`);
      else router.push(`/r/${result.requested_slug}?job=${result.job_id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
      setBusy(false);
    }
  }

  const analysed = new Map((repos ?? []).map((r) => [r.canonical_slug.toLowerCase(), r]));

  return (
    <div className="space-y-14">
      <section className="space-y-5">
        <h1 className="max-w-2xl text-3xl font-semibold tracking-tight sm:text-4xl">
          If I want to contribute here, where might I start?
        </h1>
        <p className="max-w-2xl text-lg text-neutral-600">
          Paste a public GitHub repository. RepoCompass reads its git history and pull requests and
          shows how newcomers have fared in each part of it. Every rate comes with its sample size.
        </p>
        <form onSubmit={submit} className="flex max-w-2xl flex-col gap-2 sm:flex-row">
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            aria-label="Repository URL"
            className="flex-1 rounded-lg border border-neutral-300 bg-white px-4 py-2.5 shadow-sm focus:border-neutral-900 focus:outline-none"
            required
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-neutral-900 px-5 py-2.5 font-medium text-white shadow-sm hover:bg-neutral-700 disabled:opacity-50"
          >
            {busy ? "Sending…" : "Analyse"}
          </button>
        </form>
        {error && <p className="text-red-700">{error}</p>}
        <div className="grid gap-4 pt-2 sm:grid-cols-3">
          {GETS.map(([title, text]) => (
            <div key={title}>
              <p className="font-medium">{title}</p>
              <p className="text-sm text-neutral-600">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Examples</h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {EXAMPLES.map((example) => {
            const found = analysed.get(example.slug.toLowerCase());
            return (
              <Link
                key={example.slug}
                href={`/r/${example.slug}`}
                className="group rounded-xl border border-neutral-200 bg-white p-4 shadow-sm transition hover:border-neutral-400"
              >
                <p className="text-xs font-medium tracking-wide text-neutral-500 uppercase">
                  {example.size}
                </p>
                <p className="mt-1 font-mono text-sm font-semibold break-all group-hover:underline">
                  {example.slug}
                </p>
                {example.note && <p className="text-xs text-neutral-500">{example.note}</p>}
                <p className="mt-2 text-sm text-neutral-500">
                  {found ? `Analysed, snapshot ${date(found.snapshot_at)}` : "Not analysed yet"}
                </p>
              </Link>
            );
          })}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Analysed repositories</h2>
        {reposError && <p className="text-red-700">{reposError}</p>}
        {repos === null && !reposError && <p className="text-neutral-500">Loading…</p>}
        {repos?.length === 0 && <p className="text-neutral-500">None yet.</p>}
        {repos && repos.length > 0 && (
          <ul className="divide-y divide-neutral-100 rounded-xl border border-neutral-200 bg-white">
            {repos.map((r) => (
              <li key={r.canonical_slug} className="flex flex-wrap justify-between gap-2 px-4 py-3">
                <Link href={`/r/${r.canonical_slug}`} className="font-mono text-sm hover:underline">
                  {r.canonical_slug}
                </Link>
                <span className="text-sm text-neutral-500">
                  snapshot {date(r.snapshot_at)}
                  {r.is_sampled ? " · sampled" : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
