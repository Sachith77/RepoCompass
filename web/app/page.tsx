"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Label } from "@/components/ui";
import { analyze, ApiError, getRepos, type RepoSummary } from "@/lib/api";
import { date } from "@/lib/format";

// The reference repositories from docs/BRIEF.md, by size.
const EXAMPLES = [
  { slug: "Kludex/starlette", size: "small", note: "previously encode/starlette" },
  { slug: "optuna/optuna", size: "medium", note: null },
  { slug: "kubernetes/kubernetes", size: "huge", note: null },
];

const HOW_TO_READ = [
  [
    "Where to start",
    "Each area's newcomer merge rate, with its sample size and a 95% interval, marked above, below or not clearly different from the repo average.",
  ],
  [
    "How it answers",
    "How long a first review or reply usually takes, and how often newcomer PRs got no reply at all.",
  ],
  [
    "Who is active",
    "Commit activity per area, and the people whose PRs were merged there and who reviewed there, as counts.",
  ],
];

function RepoRow({ slug, meta, note }: { slug: string; meta: string; note?: string | null }) {
  return (
    <li>
      <Link
        href={`/r/${slug}`}
        className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-line py-3 text-ink no-underline hover:bg-wash focus-visible:bg-wash"
      >
        <span className="font-mono">
          {slug}
          {note && <span className="ml-3 font-sans text-small text-muted">{note}</span>}
        </span>
        <span className="text-small text-muted">{meta}</span>
      </Link>
    </li>
  );
}

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
    <div className="space-y-16">
      <section className="max-w-[680px] space-y-5">
        <h1 className="font-serif text-display font-semibold">
          If I want to contribute here, where might I start?
        </h1>
        <p className="text-lead text-muted">
          RepoCompass reads a public repository&apos;s git history and pull requests and shows how
          newcomers have fared in each part of it, with every rate beside its sample size.
        </p>
        <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
          <label htmlFor="repo-url" className="sr-only">
            Repository URL
          </label>
          <input
            id="repo-url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            className="flex-1 rounded-md border border-control bg-white px-4 py-2.5 font-mono text-body placeholder:text-muted focus:border-accent focus:outline-none"
            required
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-accent px-5 py-2.5 font-medium text-white hover:bg-accent-strong disabled:opacity-60"
          >
            {busy ? "Sending…" : "Analyse"}
          </button>
        </form>
        {error && <p role="alert" className="font-medium">{error}</p>}
      </section>

      <section className="space-y-4">
        <Label>How to read a report</Label>
        <div className="grid border-t border-line sm:grid-cols-3">
          {HOW_TO_READ.map(([title, text], i) => (
            <div key={title} className={`py-4 sm:pr-6 ${i > 0 ? "border-t border-line sm:border-t-0 sm:border-l sm:pl-6" : ""}`}>
              <p className="font-serif text-heading font-semibold">{title}</p>
              <p className="mt-1 text-muted">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <Label>Examples</Label>
        <ul className="border-t border-line">
          {EXAMPLES.map((e) => {
            const found = analysed.get(e.slug.toLowerCase());
            const status = found ? `snapshot ${date(found.snapshot_at)}` : "not analysed yet";
            return (
              <RepoRow
                key={e.slug}
                slug={e.slug}
                note={e.note}
                meta={`${e.size.toUpperCase()} · ${status}`}
              />
            );
          })}
        </ul>
      </section>

      <section className="space-y-3">
        <Label>Analysed repositories</Label>
        {reposError && <p role="alert" className="font-medium">{reposError}</p>}
        {repos === null && !reposError && <p className="text-muted">Loading…</p>}
        {repos?.length === 0 && (
          <p className="text-muted">None yet. Paste a repository above to analyse the first one.</p>
        )}
        {repos && repos.length > 0 && (
          <ul className="border-t border-line">
            {repos.map((r) => (
              <RepoRow
                key={r.canonical_slug}
                slug={r.canonical_slug}
                meta={`snapshot ${date(r.snapshot_at)}${r.is_sampled ? " · sampled" : ""}`}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
