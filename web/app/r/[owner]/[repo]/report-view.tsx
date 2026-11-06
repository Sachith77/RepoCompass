"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import AreaCard from "@/components/area-card";
import RateChart from "@/components/rate-chart";
import { JobFailed, JobProgress, ReportSkeleton } from "@/components/job-progress";
import { AreasMap, DataAndSample, EmptyState, Lead, NotEnoughData } from "@/components/report";
import { Label } from "@/components/ui";
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

  if (error) {
    return (
      <div className="max-w-[680px] space-y-2">
        <h1 className="font-serif text-title font-semibold">
          {owner}/{repo}
        </h1>
        <p>{error}</p>
      </div>
    );
  }

  if (jobId !== null) {
    return (
      <div className="space-y-10">
        <h1 className="font-serif text-display font-semibold break-all">
          {owner}/{repo}
        </h1>
        {pollError && <p role="alert" className="font-medium">Could not check the job ({pollError}); trying again.</p>}
        {job?.state === "failed" ? <JobFailed job={job} onRetry={start} /> : <JobProgress job={job} />}
        {job?.state !== "failed" && <ReportSkeleton />}
        {job?.areas_map && (
          <section className="space-y-4">
            <div>
              <Label>Areas map</Label>
              <h2 className="font-serif text-heading font-semibold">Ready early, from git history</h2>
            </div>
            <AreasMap areas={job.areas_map} />
          </section>
        )}
      </div>
    );
  }

  if (report === undefined) return <p className="text-muted">Loading…</p>;

  if (report === null) {
    return (
      <div className="max-w-[680px] space-y-4">
        <h1 className="font-serif text-display font-semibold break-all">
          {owner}/{repo}
        </h1>
        <p className="text-lead">
          This repository has not been analysed yet. An analysis reads its git history and pull
          requests; in a measured run, Kludex/starlette took about two minutes.
        </p>
        <button
          onClick={start}
          className="rounded-md bg-accent px-4 py-2 font-medium text-white hover:bg-accent-strong"
        >
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
  const renamed = report.repo.requested_slug.toLowerCase() !== slug.toLowerCase();
  return (
    <article className="space-y-14">
      <header className="space-y-3">
        <h1 className="font-serif text-display font-semibold break-all">
          <a href={report.repo.url} className="text-ink hover:underline">
            {slug}
          </a>
        </h1>
        <p className="text-small text-muted">
          Snapshot {date(report.repo.snapshot_at)}
          {renamed && (
            <>
              {" · previously "}
              <span className="font-mono">{report.repo.requested_slug}</span>
            </>
          )}
          {report.sample.is_sampled &&
            ` · sampled, covers ${date(report.sample.covered_from)} to ${date(report.sample.covered_to)}`}
          {" · "}
          <Link href={`/method?repo=${slug}`}>How these numbers are made</Link>
        </p>
        <Lead report={report} />
      </header>

      <section className="space-y-6">
        <div className="max-w-[680px] space-y-1">
          <Label>Where to start</Label>
          <h2 className="font-serif text-title font-semibold">How each area compares with the repo</h2>
          <p className="text-muted">{w.heading}</p>
        </div>
        {w.bands.length === 0 ? (
          <EmptyState report={report} />
        ) : (
          <>
            <RateChart groups={w.bands} repoRate={w.repo_rate} />
            <div className="grid gap-5 md:grid-cols-2">
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
            {w.not_enough_data.length > 0 && <NotEnoughData report={report} />}
          </>
        )}
      </section>

      <section className="space-y-4">
        <div className="max-w-[680px] space-y-1">
          <Label>Areas map</Label>
          <h2 className="font-serif text-title font-semibold">Where work happens</h2>
          <p className="text-muted">
            Commits from git history, most active first. Excluded directories:{" "}
            {report.method.excluded_dirs.join(", ") || "none"}.
          </p>
        </div>
        <AreasMap areas={report.areas_map} />
      </section>

      <DataAndSample report={report} />

      <p className="text-small text-muted">
        Snapshot {date(report.repo.snapshot_at)} ·{" "}
        <Link href={`/method?repo=${slug}`}>Method and parameters</Link>
      </p>
    </article>
  );
}
