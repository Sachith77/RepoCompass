import { Label, Skeleton } from "@/components/ui";
import type { Job } from "@/lib/api";

// The steps a job goes through, matched to the stage the worker reports. The git stage covers
// the first two; the areas map exists once it is done.
const STEPS = [
  { title: "Clone the repository and read its history", stage: "git" },
  { title: "Map its areas", stage: "git" },
  { title: "Fetch pull requests", stage: "prs" },
  { title: "Find first-time contributors and compute rates", stage: "lookback" },
];

function currentStep(job: Job): number {
  if (job.state === "queued") return -1;
  // web jobs have no stage until the git stage is saved, so a running job starts at the clone
  if (job.stage === null) return job.state === "running" ? 0 : -1;
  if (job.stage === "git") return job.areas_map ? 2 : 0;
  if (job.stage === "prs") return 2;
  if (job.stage === "lookback") return 3;
  return STEPS.length;
}

export function JobProgress({ job }: { job: Job | null }) {
  if (job === null) return <p className="text-muted">Checking the analysis…</p>;
  const step = currentStep(job);
  return (
    <section className="max-w-[680px] space-y-4">
      <Label>Analysis in progress</Label>
      <p className="text-muted">
        {job.state === "queued"
          ? "Waiting for the worker to pick this repository up."
          : `${job.progress}% done. Large repositories take a while; this page updates by itself.`}
      </p>
      <ol className="space-y-2" aria-live="polite">
        {STEPS.map((s, i) => {
          const done = i < step;
          const now = i === step;
          return (
            <li key={s.title} className="flex items-baseline gap-3">
              <span
                aria-hidden
                className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full border ${
                  done ? "border-accent bg-accent" : now ? "border-accent" : "border-control"
                }`}
              />
              <span className={now ? "font-medium text-ink" : "text-muted"}>
                {s.title}
                {now && <span className="sr-only"> (in progress)</span>}
                {done && <span className="sr-only"> (done)</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function JobFailed({ job, onRetry }: { job: Job; onRetry: () => void }) {
  return (
    <section className="max-w-[680px] space-y-3 border-y border-line py-6">
      <Label>The analysis stopped</Label>
      <p>{job.last_error}</p>
      <p className="text-muted">
        Trying again continues from the last saved step when its data is less than 24 hours old;
        otherwise it starts again from the beginning.
      </p>
      <button
        onClick={onRetry}
        className="rounded-md bg-accent px-4 py-2 font-medium text-white hover:bg-accent-strong"
      >
        Try again
      </button>
    </section>
  );
}

export function ReportSkeleton() {
  return (
    <div className="space-y-10" aria-hidden>
      <div className="max-w-[680px]">
        <Skeleton lines={3} />
      </div>
      <div className="space-y-3">
        <Skeleton lines={1} />
        <div className="h-40 rounded-md border border-dashed border-line" />
      </div>
    </div>
  );
}
