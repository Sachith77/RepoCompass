"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import AreaCard from "@/components/area-card";
import RateChart from "@/components/rate-chart";
import { AreasMap, DataAndSample, EmptyState, SummaryCard } from "@/components/report";
import { analyze, ApiError, getJob, getReport, type Job, type Report } from "@/lib/api";
import { date } from "@/lib/format";

const POLL_MS = 2000;

type Props = { owner: string; repo: string; initialJobId: number | null };

export default function ReportView({ owner, repo, initialJobId }: Props) {
  const router = useRouter();
  const [jobId, setJobId] = useState<number | null>(initialJobId);
  // bumped on every retry, so polling restarts even when the API returns the same job id
  const [attempt, setAttempt] = useState(0);
  const [job, setJob] = useState<Job | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  // load the stored report when no job is being followed
  useEffect(() => {
    if (jobId !== null) return;
    let cancelled = false;
    getReport(owner, repo)
      .then((r) => !cancelled && setReport(r))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [owner, repo, jobId]);

  // follow a job until it is done or failed; a failed request is retried, not fatal
  useEffect(() => {
    if (jobId === null) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const current = await getJob(jobId);
        if (cancelled) return;
        setJob(current);
        setPollError(null);
        if (current.state === "done") {
          setReport(undefined); // "Loading…" until the finished report arrives
          setJobId(null);
          router.replace(`/r/${owner}/${repo}`);
          return;
        }
        if (current.state === "failed") return;
      } catch (e) {
        if (cancelled) return;
        setPollError(e instanceof Error ? e.message : String(e));
      }
      timer = setTimeout(poll, POLL_MS);
    };
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId, attempt, owner, repo, router]);

  async function start() {
    setError(null);
    try {
      const result = await analyze(`${owner}/${repo}`);
      if (result.status === "cached") {
        setJob(null);
        setJobId(null);
        setReport(result.report);
      } else {
        setJob(null);
        setJobId(result.job_id);
        setAttempt((n) => n + 1);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    }
  }

  if (error) return <p className="text-red-700">{error}</p>;

  if (jobId !== null) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold">
          {owner}/{repo}
        </h1>
        {pollError && (
          <p className="text-red-700">Could not check the job ({pollError}); trying again.</p>
        )}
        <JobProgress job={job} onRetry={start} />
        {job?.areas_map && (
          <section className="space-y-2">
            <h2 className="text-lg font-semibold">Areas map (ready early, from git history)</h2>
            <AreasMap areas={job.areas_map} />
          </section>
        )}
      </div>
    );
  }

  if (report === undefined) return <p className="text-neutral-500">Loading…</p>;

  if (report === null) {
    return (
      <div className="space-y-3">
        <h1 className="text-2xl font-semibold">
          {owner}/{repo}
        </h1>
        <p>This repository has not been analysed yet.</p>
        <button onClick={start} className="rounded bg-neutral-900 px-4 py-2 text-white">
          Analyse it
        </button>
      </div>
    );
  }

  return <ReportBody report={report} />;
}

function ReportBody({ report }: { report: Report }) {
  const slug = report.repo.canonical_slug;
  const w = report.where_to_start;
  const params = report.method.parameters;
  const people = new Map(report.areas_map.map((a) => [a.area, a]));
  return (
    <div className="space-y-10">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight break-all">
          <a href={report.repo.url} className="hover:underline">
            {slug}
          </a>
        </h1>
        <p className="text-sm text-neutral-500">
          Snapshot {date(report.repo.snapshot_at)}
          {report.repo.requested_slug.toLowerCase() !== slug.toLowerCase() &&
            ` · requested as ${report.repo.requested_slug}`}
          {" · "}
          <Link href={`/method?repo=${slug}`} className="text-blue-700 hover:underline">
            How these numbers are made
          </Link>
        </p>
        {report.sample.is_sampled && (
          <p className="inline-block rounded-lg bg-amber-50 px-3 py-1.5 text-sm text-amber-900 ring-1 ring-amber-600/20">
            Sampled: covers {date(report.sample.covered_from)} to {date(report.sample.covered_to)}.
            Details under Data and sample.
          </p>
        )}
      </header>

      <SummaryCard report={report} />

      <section className="space-y-4">
        <div>
          <h2 className="text-xl font-semibold">Where to start</h2>
          <p className="text-neutral-600">{w.heading}</p>
        </div>
        {w.bands.length === 0 ? (
          <EmptyState report={report} />
        ) : (
          <>
            <div className="rounded-xl border border-neutral-200 bg-white p-4">
              <RateChart groups={w.bands} repoRate={w.repo_rate} />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              {w.bands.flatMap((group) =>
                group.areas.map((area) => (
                  <AreaCard
                    key={area.area}
                    area={area}
                    lead={w.lead_response_measure}
                    reviewers={people.get(area.area)?.top_reviewers ?? []}
                    contributors={people.get(area.area)?.top_contributors ?? []}
                    noResponseDays={params.no_response_days}
                    staleDays={params.stale_open_days}
                  />
                )),
              )}
            </div>
            {w.not_enough_data.length > 0 && (
              <p className="text-sm text-neutral-500">
                Not enough data (fewer than {params.min_sample} mature newcomer PRs):{" "}
                {w.not_enough_data.map((a) => `${a.area} (${a.mature_newcomer_prs})`).join(" · ")}
              </p>
            )}
          </>
        )}
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-xl font-semibold">Areas map</h2>
          <p className="text-sm text-neutral-600">
            Commit activity from git history. Excluded directories:{" "}
            {report.method.excluded_dirs.join(", ") || "none"}.
          </p>
        </div>
        <AreasMap areas={report.areas_map} />
      </section>

      <DataAndSample report={report} />
    </div>
  );
}

function JobProgress({ job, onRetry }: { job: Job | null; onRetry: () => void }) {
  if (job === null) return <p className="text-neutral-500">Checking the job…</p>;
  if (job.state === "failed") {
    return (
      <div className="space-y-2 rounded border border-red-200 bg-red-50 p-4">
        <p>The analysis failed: {job.last_error}</p>
        <button onClick={onRetry} className="rounded bg-neutral-900 px-4 py-2 text-white">
          Try again
        </button>
        <p className="text-sm text-neutral-600">
          A job whose snapshot is less than 24 hours old continues from its checkpoint; an older
          one starts again.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <p>
        Job {job.id}: {job.state}
        {job.stage ? `, stage ${job.stage}` : ""} — {job.progress}%
      </p>
      <div className="h-2 w-full rounded bg-neutral-200">
        <div className="h-2 rounded bg-neutral-800" style={{ width: `${job.progress}%` }} />
      </div>
      <p className="text-sm text-neutral-500">
        Large repositories take a long time. This page updates by itself.
      </p>
    </div>
  );
}
