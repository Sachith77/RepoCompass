// The summary card's sentences, built by fixed rules from report fields only. Every
// number in them is a field of the report, rounded; nothing is estimated here.

import type { Report } from "@/lib/api";
import { ABOVE, BELOW } from "@/lib/bands";
import { durationWords, listWords, percent } from "@/lib/format";

export function summarise(report: Report): string[] {
  const w = report.where_to_start;
  const sentences: string[] = [];

  const p = report.method.parameters;
  if (w.repo_rate === null) {
    sentences.push("There are no finished newcomer PRs here yet, so no merge rate can be given.");
  } else {
    sentences.push(
      `Newcomer PRs here get merged ${percent(w.repo_rate)} of the time ` +
        `(${w.repo_mature_newcomer_prs} newcomer PRs that were merged or closed and are at least ` +
        `${p.maturity_days} days old).`,
    );
  }

  // a median only describes the PRs that got an answer, so it always comes with the share
  // that got none
  const formal = w.lead_response_measure === "formal review";
  const median = formal
    ? w.repo_median_hours_first_formal_review
    : w.repo_median_hours_first_human_response;
  const n = formal ? w.repo_formal_review_prs : w.repo_human_response_prs;
  if (median != null && n > 0) {
    // when few PRs get a formal review, say so first: that is why this counts any human response
    const intro =
      formal || w.formal_review_coverage == null
        ? ""
        : `Fewer than half of PRs here get a formal review (${percent(w.formal_review_coverage)}), so this ` +
          "counts any human response: of";
    const what = formal ? "a formal review" : intro ? "one" : "a human response";
    let text = intro
      ? `${intro} the ${n} newcomer PRs that got ${what}, half got it within ${durationWords(median)}`
      : `Of the ${n} newcomer PRs that got ${what}, half got one within ${durationWords(median)}`;
    if (w.repo_no_response_share != null && w.repo_no_response_base_prs > 0) {
      text +=
        `; ${percent(w.repo_no_response_share)} of ${w.repo_no_response_base_prs} finished ` +
        `newcomer PRs got no human response within ${p.no_response_days} days`;
    }
    sentences.push(`${text}.`);
  }

  const names = (band: string) =>
    w.bands.find((b) => b.band === band)?.areas.map((a) => a.area) ?? [];
  const above = names(ABOVE);
  const below = names(BELOW);
  const minSample = report.method.parameters.min_sample;
  if (w.bands.length === 0) {
    sentences.push(
      `No area has enough data yet (at least ${minSample} mature newcomer PRs) ` +
        "to compare with the repo average.",
    );
  } else if (above.length > 0) {
    const one = above.length === 1;
    let text = `${one ? "Area" : "Areas"} ${listWords(above)} ${one ? "stands" : "stand"} out above the repo average`;
    if (below.length > 0) text += `; ${listWords(below)} ${below.length === 1 ? "is" : "are"} below it`;
    sentences.push(`${text}.`);
  } else if (below.length > 0) {
    const verb = below.length === 1 ? "is" : "are";
    sentences.push(
      `No area stands out clearly above the repo average; ${listWords(below)} ${verb} below it.`,
    );
  } else {
    sentences.push("No area stands out clearly from the repo average.");
  }
  return sentences;
}
