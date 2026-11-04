"""The report, read from stored rows. `build_report` is pure, so its shape is testable.

Order of the report (docs/BRIEF.md, "v0 report"): where to start, the areas map,
the sample note, then the method summary. Inside a band, areas are alphabetical:
no ranking and no implied order. Nobody is called a maintainer or owner.

Every parameter shown comes from the analysis itself (`repos.parameters`), never
from today's settings, so the labels always describe the numbers next to them.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from repocompass.config import Settings
from repocompass.db import connect
from repocompass.metrics import ABOVE, BELOW, NO_CLEAR_DIFFERENCE, NOT_ENOUGH_DATA

__all__ = [
    "HEADING",
    "OutdatedReport",
    "build_report",
    "lead_response_measure",
    "list_repos",
    "load_report",
]

HEADING = "Based on historical contribution patterns, these areas may be better starting points."
BAND_ORDER = (ABOVE, NO_CLEAR_DIFFERENCE, BELOW)
EXAMPLES_PER_AREA = 3
FORMAL_REVIEW = "formal review"
HUMAN_RESPONSE = "human response"

# By canonical name, by the name it was stored under, or by any name a finished job
# was requested under (a renamed repository keeps answering to its old name).
FIND_REPO = """
SELECT * FROM repos
 WHERE lower(canonical_slug) = %(slug)s OR lower(requested_slug) = %(slug)s
    OR id IN (SELECT repo_id FROM jobs WHERE state = 'done' AND lower(requested_slug) = %(slug)s)
 ORDER BY (lower(canonical_slug) = %(slug)s) DESC LIMIT 1
"""
AREAS = "SELECT * FROM area_stats WHERE repo_id = %s ORDER BY area"
EXAMPLES = f"""
SELECT area, number FROM (
    SELECT a.area, p.number,
           row_number() OVER (PARTITION BY a.area ORDER BY p.merged_at DESC, p.number) AS n
      FROM pr_areas a JOIN prs p ON p.repo_id = a.repo_id AND p.number = a.pr_number
     WHERE a.repo_id = %s AND p.is_newcomer AND p.is_merged AND p.files_complete
) ranked WHERE n <= {EXAMPLES_PER_AREA} ORDER BY area, n
"""
# Coverage uses mature PRs only (old enough to have been reviewed), as Phase 0 measured it.
# The last two counts are the repo-wide no-response share, by the rule in metrics.py:
# mature newcomer PRs with complete files and known response times, and of those the
# ones with no human response within no_response_days.
PR_COUNTS = """
SELECT count(*) FILTER (WHERE old AND response_times_complete
                          AND first_formal_review_at IS NOT NULL),
       count(*) FILTER (WHERE old AND response_times_complete),
       count(*) FILTER (WHERE NOT files_complete),
       count(*) FILTER (WHERE NOT response_times_complete),
       count(*) FILTER (WHERE base AND (first_human_response_at IS NULL OR late)),
       count(*) FILTER (WHERE base)
  FROM (SELECT *, old AND state <> 'OPEN' AND is_newcomer AND files_complete
                  AND response_times_complete AS base
          FROM (SELECT p.*,
                       p.created_at <= r.snapshot_at
                         - make_interval(days => (r.parameters ->> 'maturity_days')::int) AS old,
                       p.first_human_response_at - p.created_at
                         > make_interval(days => (r.parameters ->> 'no_response_days')::int) AS late
                  FROM prs p JOIN repos r ON r.id = p.repo_id
                 WHERE p.repo_id = %s) aged) counted
"""


class OutdatedReport(ValueError):
    """A stored analysis from an older schema, without the parameters it ran with."""


# Repo-wide medians over the same PRs as the per-area ones in metrics.py: newcomer PRs
# with complete files and known response times that got that response.
REPO_MEDIANS = """
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY review_h)
           FILTER (WHERE review_h IS NOT NULL),
       count(review_h),
       percentile_cont(0.5) WITHIN GROUP (ORDER BY response_h)
           FILTER (WHERE response_h IS NOT NULL),
       count(response_h)
  FROM (SELECT extract(epoch FROM first_formal_review_at - created_at) / 3600 AS review_h,
               extract(epoch FROM first_human_response_at - created_at) / 3600 AS response_h
          FROM prs
         WHERE repo_id = %s AND is_newcomer AND files_complete AND response_times_complete) hours
"""
EMPTY_RESPONSES: dict[str, Any] = {
    "repo_median_hours_first_formal_review": None,
    "repo_formal_review_prs": 0,
    "repo_median_hours_first_human_response": None,
    "repo_human_response_prs": 0,
    "repo_no_response_share": None,
    "repo_no_response_base_prs": 0,
}


def lead_response_measure(reviewed: int, total: int, threshold: float) -> str:
    """Lead with formal review unless too few PRs get one (some repos approve in comments)."""
    if total and reviewed / total < threshold:
        return HUMAN_RESPONSE
    return FORMAL_REVIEW


def _area_entry(
    row: dict[str, Any], slug: str, examples: list[int], threshold: float
) -> dict[str, Any]:
    flagged = row["author_concentration_flag"]
    return {
        "area": row["area"],
        "band": row["band"],
        "merge_rate": row["merge_rate"],
        "mature_newcomer_prs": row["mature_newcomer_prs"],
        "merged_prs": row["merged_prs"],
        "wilson_interval": [row["wilson_low"], row["wilson_high"]],
        "distinct_newcomer_authors": row["distinct_newcomer_authors"],
        "top_author_pr_share": row["top_author_pr_share"],
        "author_concentration_flag": flagged,
        "concentration_note": (
            f"The sample is dominated by one contributor (more than {threshold:.0%} of these "
            "PRs), so the merge rate describes one person's experience more than the area's."
            if flagged
            else None
        ),
        "stale_open_newcomer_prs": row["stale_open_newcomer_prs"],
        "median_hours_first_formal_review": row["median_hours_first_formal_review"],
        "formal_review_prs": row["formal_review_prs"],
        "median_hours_first_human_response": row["median_hours_first_human_response"],
        "human_response_prs": row["human_response_prs"],
        "no_response_share": row["no_response_share"],
        "no_response_base_prs": row["no_response_base_prs"],
        "example_merged_newcomer_prs": [
            {"number": n, "url": f"https://github.com/{slug}/pull/{n}"} for n in examples
        ],
    }


def _sample_note(repo: dict[str, Any], cap: int, incomplete: int, unknown: int) -> str:
    covered = f"{repo['sample_first_created']} to {repo['sample_last_created']}"
    if repo["is_sampled"]:
        text = (
            f"Sampled: at least one month had more than {cap} human PRs, and only its newest "
            f"{cap} were kept. The sample covers {covered}; it is not every PR."
        )
    else:
        text = f"Every human-authored PR created in the window was kept, covering {covered}."
    return (
        f"{text} {incomplete} PRs whose changed files could not all be fetched are left out of "
        f"every area figure, and {unknown} PRs with unknown response times are left out of the "
        "response figures."
    )


def build_report(
    repo: dict[str, Any],
    areas: list[dict[str, Any]],
    examples: dict[str, list[int]],
    pr_counts: tuple[int, int, int, int],
    repo_responses: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`pr_counts`: (mature PRs with a formal review, mature PRs, incomplete, unknown).

    `repo_responses`: the repo-wide response fields named in EMPTY_RESPONSES.
    """
    slug = repo["canonical_slug"]
    params = repo["parameters"]
    if not params:
        raise OutdatedReport(f"the stored analysis of {slug} has no parameters; analyse it again")
    threshold = params["author_concentration_threshold"]
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in areas:
        if row["band"] != NOT_ENOUGH_DATA:
            entry = _area_entry(row, slug, examples.get(row["area"], []), threshold)
            grouped[row["band"]].append(entry)
    reviewed, mature, incomplete, unknown = pr_counts
    responses = {**EMPTY_RESPONSES, **(repo_responses or {})}
    return {
        "repo": {
            "requested_slug": repo["requested_slug"],
            "canonical_slug": slug,
            "url": f"https://github.com/{slug}",
            "default_branch": repo["default_branch"],
            "snapshot_at": repo["snapshot_at"],
        },
        "where_to_start": {
            "heading": HEADING,
            "repo_rate": repo["repo_merge_rate"],
            "repo_mature_newcomer_prs": repo["repo_mature_newcomer_prs"],
            "formal_review_coverage": reviewed / mature if mature else None,
            "lead_response_measure": lead_response_measure(
                reviewed, mature, params["formal_review_coverage_threshold"]
            ),
            **responses,
            "bands": [{"band": b, "areas": grouped[b]} for b in BAND_ORDER if grouped[b]],
            "not_enough_data": [
                {"area": r["area"], "mature_newcomer_prs": r["mature_newcomer_prs"]}
                for r in areas
                if r["band"] == NOT_ENOUGH_DATA
            ],
        },
        "areas_map": [
            {
                "area": r["area"],
                "commits_90d": r["commits_90d"],
                "commits_12mo": r["commits_12mo"],
                "commit_authors_12mo": r["commit_authors_12mo"],
                "activity_band": r["activity_band"],
                "top_contributors": r["top_contributors"],
                "top_reviewers": r["top_reviewers"],
            }
            for r in areas
        ],
        "sample": {
            "window_start": repo["window_start"],
            "window_end": repo["window_end"],
            "total_prs": repo["total_prs_in_window"],
            "bot_or_non_user_prs_dropped": repo["bot_prs_in_window"],
            "sampled_prs": repo["sampled_prs"],
            "is_sampled": repo["is_sampled"],
            "covered_from": repo["sample_first_created"],
            "covered_to": repo["sample_last_created"],
            "prs_with_incomplete_files": incomplete,
            "prs_with_unknown_response_times": unknown,
            "per_month": repo["prs_per_month"],
            "note": _sample_note(repo, params["monthly_sample_cap"], incomplete, unknown),
        },
        "method": {
            "area_rule": repo["area_depths"],
            "excluded_dirs": repo["excluded_dirs"],
            "sweep_commits_excluded": repo["sweep_commits_excluded"],
            "parameters": params,
        },
    }


def _rows(cur: Any) -> list[dict[str, Any]]:
    names = [c.name for c in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def _find(cur: Any, owner: str, name: str) -> dict[str, Any] | None:
    cur.execute(FIND_REPO, {"slug": f"{owner}/{name}".lower()})
    found = _rows(cur)
    return found[0] if found else None


def load_report(settings: Settings, owner: str, name: str) -> dict[str, Any] | None:
    """The stored report for a repository (by any of its names), or None."""
    with connect(settings.database_url) as conn, conn.cursor() as cur:
        repo = _find(cur, owner, name)
        if repo is None:
            return None
        cur.execute(AREAS, (repo["id"],))
        areas = _rows(cur)
        cur.execute(EXAMPLES, (repo["id"],))
        examples: defaultdict[str, list[int]] = defaultdict(list)
        for area, number in cur.fetchall():
            examples[area].append(number)
        cur.execute(PR_COUNTS, (repo["id"],))
        row = cur.fetchone()
        cur.execute(REPO_MEDIANS, (repo["id"],))
        med = cur.fetchone()
    row = tuple(int(v) for v in row) if row else (0, 0, 0, 0, 0, 0)
    counts = (row[0], row[1], row[2], row[3])
    responses = dict(EMPTY_RESPONSES)
    if med:
        responses.update(
            repo_median_hours_first_formal_review=_float(med[0]),
            repo_formal_review_prs=int(med[1]),
            repo_median_hours_first_human_response=_float(med[2]),
            repo_human_response_prs=int(med[3]),
        )
    if row[5]:
        responses.update(repo_no_response_share=row[4] / row[5], repo_no_response_base_prs=row[5])
    return build_report(repo, areas, dict(examples), counts, responses)


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def list_repos(settings: Settings) -> list[dict[str, Any]]:
    with connect(settings.database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT canonical_slug, requested_slug, snapshot_at, is_sampled FROM repos"
            " ORDER BY lower(canonical_slug)"
        )
        rows = _rows(cur)
    for row in rows:
        row["report_url"] = f"/repos/{row['canonical_slug']}/report"
    return rows
