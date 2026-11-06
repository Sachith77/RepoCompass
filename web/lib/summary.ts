// The lead paragraph, built by fixed rules from report fields only. Every number is a field of the
// report, rounded; nothing is estimated. Each sentence is a list of parts so key numbers can be
// set in semibold and area names in monospace.

import type { Report } from "@/lib/api";
import { ABOVE, BELOW } from "@/lib/bands";
import { durationWords, percent } from "@/lib/format";

export type Part = { text: string; strong?: boolean; mono?: boolean };
export type Sentence = Part[];

const t = (text: string): Part => ({ text });
const b = (text: string): Part => ({ text, strong: true });
const m = (text: string): Part => ({ text, mono: true, strong: true });

function areaList(names: string[]): Part[] {
  const out: Part[] = [];
  names.forEach((name, i) => {
    if (i > 0) out.push(t(i === names.length - 1 ? " and " : ", "));
    out.push(m(name));
  });
  return out;
}

const verb = (count: number, one: string, many: string) => t(count === 1 ? one : many);

export function summarise(report: Report): Sentence[] {
  const w = report.where_to_start;
  const p = report.method.parameters;
  const out: Sentence[] = [];

  if (w.repo_rate === null) {
    out.push([t("There are no finished newcomer PRs here yet, so no merge rate can be given.")]);
  } else {
    out.push([
      t("Newcomer PRs get merged "),
      b(percent(w.repo_rate)),
      t(" of the time ("),
      b(String(w.repo_mature_newcomer_prs)),
      t(" finished newcomer PRs)."),
    ]);
  }

  // the share with no answer at all comes after the median, which cannot show it
  const formal = w.lead_response_measure === "formal review";
  const median = formal
    ? w.repo_median_hours_first_formal_review
    : w.repo_median_hours_first_human_response;
  const n = formal ? w.repo_formal_review_prs : w.repo_human_response_prs;
  if (median != null && n > 0) {
    // the median covers only PRs that got an answer, so the sentence says so
    const time = [
      t("a median of "),
      b(durationWords(median)),
      t(", over the "),
      b(String(n)),
      t(" newcomer PRs that got one."),
    ];
    if (formal) {
      out.push([t("A first formal review takes "), ...time]);
    } else if (w.formal_review_coverage == null) {
      out.push([t("Response time uses any human reply: "), ...time]);
    } else {
      out.push([
        t("Only "),
        b(percent(w.formal_review_coverage)),
        t(" of PRs get a formal review, so response time uses any human reply: "),
        ...time,
      ]);
    }
  }
  if (w.repo_no_response_share != null && w.repo_no_response_base_prs > 0) {
    out.push([
      b(percent(w.repo_no_response_share)),
      t(" of "),
      b(String(w.repo_no_response_base_prs)),
      t(` finished newcomer PRs got no reply within ${p.no_response_days} days.`),
    ]);
  }

  const names = (band: string) =>
    w.bands.find((g) => g.band === band)?.areas.map((a) => a.area) ?? [];
  const above = names(ABOVE);
  const below = names(BELOW);
  if (w.bands.length === 0) {
    out.push([
      t(`No area has enough data yet (at least ${p.min_sample} finished newcomer PRs) `),
      t("to compare with the repo average."),
    ]);
  } else if (above.length > 0) {
    const s: Sentence = [
      ...areaList(above),
      verb(above.length, " stands", " stand"),
      t(" out above the repo average"),
    ];
    if (below.length > 0) {
      s.push(t("; "), ...areaList(below), verb(below.length, " is", " are"), t(" below it"));
    }
    out.push([...s, t(".")]);
  } else if (below.length > 0) {
    out.push([
      t("No area stands out above the repo average; "),
      ...areaList(below),
      verb(below.length, " is", " are"),
      t(" below it."),
    ]);
  } else {
    out.push([t("No area stands out clearly from the repo average.")]);
  }
  return out;
}
