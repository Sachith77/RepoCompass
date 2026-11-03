# ADR-0008: An analysis is one full rebuild, stored in one transaction

Status: accepted, 2026-11-03

Chose to run the git stage, then the PR stage, and only then replace all of a repository's rows
(`repos`, `prs`, `pr_areas`, `area_stats`) in a single transaction, over writing each stage's rows as
soon as that stage finishes.

Why: the rows depend on each other. Every band compares an area with the repo rate, the repo rate
depends on every PR's newcomer flag, and the flags depend on a lookback over all authors. Writing stage
by stage would leave a window where a reader sees this run's activity next to the last run's merge
rates, which reads as one valid report but is not. It is the same risk ADR-0007 avoids. Until the
final transaction, everything fetched lives in `jobs.checkpoint`, saved after the git stage, every PR
page and every lookback request, so an interrupted job resumes instead of restarting. Each PR is kept
as per-area file counts, never paths, so the checkpoint stays small: measured at 33,730 bytes as
stored (238,579 bytes of JSON) for `Kludex/starlette`, 511 PRs (`results/m3/analyze_starlette.txt`).
`ingest-git` is a developer command that stores nothing.

Trade-off: the report appears only at the end. The areas map is already in the checkpoint after the
git stage, so `GET /jobs/{id}` can still show it early.

Would revisit if: one transaction grew too large to hold comfortably. The cap bounds it: at most 250
PRs per calendar month, and a 365-day window touches at most 13 months, so at most 3,250 PR rows.
