import { BandMarker } from "@/components/ui";
import type { BandedArea, Person } from "@/lib/api";
import { hours, percent, plural, shortDuration } from "@/lib/format";

type Props = {
  area: BandedArea;
  lead: string;
  reviewers: Person[];
  contributors: Person[];
  noResponseDays: number;
  staleDays: number;
};

function people(list: Person[], unit: string): string {
  if (list.length === 0) return "none recorded";
  return list.map((p) => `${p.login} (${p.count} ${unit}${p.count === 1 ? "" : "s"})`).join(", ");
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-x-3 sm:grid-cols-[13rem_1fr] md:grid-cols-1 lg:grid-cols-[13rem_1fr]">
      <dt className="text-muted">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export default function AreaCard(props: Props) {
  const { area, lead, reviewers, contributors, noResponseDays, staleDays } = props;
  const formal = lead === "formal review";
  const leadMedian = formal
    ? area.median_hours_first_formal_review
    : area.median_hours_first_human_response;
  const [low, high] = area.wilson_interval;
  const stale = area.stale_open_newcomer_prs;
  return (
    <article className="flex flex-col gap-4 rounded-md border border-line p-5">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-mono text-body font-semibold break-all">{area.area}</h3>
        <BandMarker band={area.band} />
      </header>

      <p className="flex flex-wrap items-baseline gap-x-2">
        <span className="font-serif text-title font-semibold">{percent(area.merge_rate)}</span>
        <span className="text-muted">
          merged · {area.merged_prs} of {area.mature_newcomer_prs} ·{" "}
          {plural(area.distinct_newcomer_authors, "author")}
        </span>
      </p>

      <p>
        {formal ? "first review" : "first reply"} {shortDuration(leadMedian)} ·{" "}
        {percent(area.no_response_share)} got no reply in {noResponseDays} days
      </p>

      <dl className="space-y-1.5 text-small">
        <Row label="Reviewers to tag">{people(reviewers.slice(0, 3), "review")}</Row>
        {area.example_merged_newcomer_prs.length > 0 && (
          <Row label="Merged newcomer PRs to read">
            {area.example_merged_newcomer_prs.map((pr, i) => (
              <span key={pr.number}>
                {i > 0 && ", "}
                <a href={pr.url} className="hover:underline">
                  #{pr.number}
                </a>
              </span>
            ))}
          </Row>
        )}
      </dl>

      {(area.concentration_note || stale > 0) && (
        <div className="space-y-1 text-small text-muted">
          {area.concentration_note && <p>Note: {area.concentration_note}</p>}
          {stale > 0 && (
            <p>
              Note: {stale} newcomer PR{stale === 1 ? "" : "s"} still open after more than{" "}
              {staleDays} days.
            </p>
          )}
        </div>
      )}

      <details className="border-t border-line pt-3 text-small">
        <summary className="text-muted hover:text-ink">Details</summary>
        <dl className="mt-3 space-y-1.5">
          <Row label="95% interval">
            {percent(low)} to {percent(high)}
          </Row>
          <Row label="Sample">
            {area.mature_newcomer_prs} finished newcomer PRs from{" "}
            {plural(area.distinct_newcomer_authors, "author")}
          </Row>
          <Row label="First formal review">
            median {hours(area.median_hours_first_formal_review)} (n={area.formal_review_prs})
          </Row>
          <Row label="First human reply">
            median {hours(area.median_hours_first_human_response)} (n={area.human_response_prs})
          </Row>
          <Row label={`No reply in ${noResponseDays} days`}>
            {percent(area.no_response_share)} (n={area.no_response_base_prs})
          </Row>
          <Row label="Stale open">
            {stale} (open more than {staleDays} days)
          </Row>
          <Row label="Key contributors">{people(contributors, "merged PR")}</Row>
          <Row label="All reviewers">{people(reviewers, "review")}</Row>
        </dl>
      </details>
    </article>
  );
}
