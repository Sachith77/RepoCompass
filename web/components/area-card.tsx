import type { BandedArea, Person } from "@/lib/api";
import { bandStyle, sentenceCase } from "@/lib/bands";
import { hours, percent, shortDuration } from "@/lib/format";

type Props = {
  area: BandedArea;
  lead: string;
  reviewers: Person[];
  contributors: Person[];
  noResponseDays: number;
  staleDays: number;
};

const names = (people: Person[]) =>
  people.length === 0 ? "–" : people.map((p) => `${p.login} (${p.count})`).join(", ");

export default function AreaCard({
  area,
  lead,
  reviewers,
  contributors,
  noResponseDays,
  staleDays,
}: Props) {
  const formal = lead === "formal review";
  const leadMedian = formal ? area.median_hours_first_formal_review : area.median_hours_first_human_response;
  const [low, high] = area.wilson_interval;
  return (
    <article className="flex flex-col gap-3 rounded-xl border border-neutral-200 bg-white p-4 shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-mono text-sm font-semibold break-all">{area.area}</h3>
        <div className="flex items-center gap-1.5">
          {area.concentration_note && (
            <span
              title={area.concentration_note}
              className="cursor-help rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-amber-600/20 ring-inset"
            >
              Dominated by one contributor
            </span>
          )}
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${bandStyle(area.band).pill}`}>
            {sentenceCase(area.band)}
          </span>
        </div>
      </header>

      <p>
        <span className="text-3xl font-semibold tracking-tight">{percent(area.merge_rate)}</span>{" "}
        <span className="text-neutral-600">
          merged ({area.merged_prs} of {area.mature_newcomer_prs}, from{" "}
          {area.distinct_newcomer_authors} authors)
        </span>
      </p>

      <p className="text-sm text-neutral-700">
        {formal ? "first review" : "first response"} {shortDuration(leadMedian)} ·{" "}
        {percent(area.no_response_share)} got no human response in {noResponseDays} days
      </p>
      {area.stale_open_newcomer_prs > 0 && (
        <p className="text-sm text-neutral-700">
          {area.stale_open_newcomer_prs} newcomer PR{area.stale_open_newcomer_prs === 1 ? "" : "s"}{" "}
          still open after more than {staleDays} days
        </p>
      )}

      <dl className="space-y-1 text-sm">
        <div>
          <dt className="inline text-neutral-500">Frequent reviewers (reviews): </dt>
          <dd className="inline">{names(reviewers.slice(0, 3))}</dd>
        </div>
        {area.example_merged_newcomer_prs.length > 0 && (
          <div>
            <dt className="inline text-neutral-500">Merged newcomer PRs to read: </dt>
            <dd className="inline">
              {area.example_merged_newcomer_prs.map((pr, i) => (
                <span key={pr.number}>
                  {i > 0 && ", "}
                  <a href={pr.url} className="text-blue-700 hover:underline">
                    #{pr.number}
                  </a>
                </span>
              ))}
            </dd>
          </div>
        )}
      </dl>

      <details className="text-sm text-neutral-700">
        <summary className="cursor-pointer text-neutral-500 select-none">Details</summary>
        <ul className="mt-2 space-y-1">
          <li>
            95% interval {percent(low)}–{percent(high)}; {area.mature_newcomer_prs} mature newcomer PRs
            from {area.distinct_newcomer_authors} distinct authors
          </li>
          {area.concentration_note && <li>{area.concentration_note}</li>}
          <li>
            {area.stale_open_newcomer_prs} stale open (newcomer PRs open more than {staleDays} days)
          </li>
          <li>
            Median {hours(area.median_hours_first_formal_review)} to first formal review (n=
            {area.formal_review_prs})
          </li>
          <li>
            Median {hours(area.median_hours_first_human_response)} to first human response (n=
            {area.human_response_prs})
          </li>
          <li>
            No human response within {noResponseDays} days: {percent(area.no_response_share)} (n=
            {area.no_response_base_prs})
          </li>
          <li>Key contributors (merged PRs): {names(contributors)}</li>
          <li>Reviewers (reviews): {names(reviewers)}</li>
        </ul>
      </details>
    </article>
  );
}
