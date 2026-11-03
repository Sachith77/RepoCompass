# ADR-0007: No incremental refresh CLI in v0; re-analyse whole repositories

Status: accepted, 2026-11-03

This was the remaining provisional item in `docs/BRIEF.md`. Chose full re-analysis over a refresh CLI
that ingests only PRs created since the last run.

Why: the saving is small and the correctness risk is real. A full medium-repo analysis measured 56 s
cold, and re-running it needs no clone (the clone is already on disk and only needs a fetch), so a
refresh saves tens of seconds on the repositories anyone will actually re-run. Against that, almost
every stored value is window-dependent: the 12-month window slides, so old PRs leave the sample; the
30-day maturity rule promotes PRs as they age; `is_newcomer` depends on whether an *earlier* PR by that
author has since merged, so adding new rows can invalidate old ones; and the repo rate that every band
is compared against moves whenever any of those change. An incremental path would have to recompute
most of the table anyway, while carrying the risk of a half-updated snapshot that reads as valid.

Trade-off: re-analysing kubernetes costs the full 16.4 minutes. Acceptable, because it is a background
job and nothing waits on it.

Would revisit if: the nightly-refresh stretch item is approved and runs across many repositories, where
the aggregate cost would start to matter — and even then the cheaper fix is to refresh fewer
repositories less often, not to make one refresh incremental.
