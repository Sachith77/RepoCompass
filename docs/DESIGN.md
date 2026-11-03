# RepoCompass design

Scope: v0 as defined in `docs/BRIEF.md` after the Phase 0 decisions. Every timing quoted here was
measured on 2026-11-03 and is recorded in `results/phase0/`.

## 1. The question and the shape of the answer

One question: *if I want to contribute to this repository, where might I start?*

The answer is a set of **areas** (directories), each carrying a mature newcomer merge rate, a sample
size, a 95% Wilson interval, and a **band** saying whether that interval sits above, below, or
overlapping the repository's own newcomer merge rate. Nothing is ranked 1-2-3, because Phase 0 showed
adjacent intervals overlap almost entirely at the sample sizes available (ADR-0003).

## 2. Components

```
            POST /analyze                 claims job
 browser ──────────────► FastAPI ──► jobs table ──► worker
    ▲                      │  ▲                       │
    │  GET report/jobs     │  │                       │ writes
    └──────────────────────┘  └───────── Postgres ◄────┘
                                            ▲
                          git clone  ────────┘
                          GitHub GraphQL ────┘
```

Five pieces, one process each: the FastAPI service, one worker, Postgres, the git CLI, and the Next.js
pages. The API never calls GitHub; it only reads and writes Postgres and enqueues jobs. All network
work happens in the worker. That split is what makes the queue decision (ADR-0005) cheap to explain:
the API stays fast and stateless, and every slow or failure-prone thing lives in one place.

## 3. Pipeline

The worker runs four stages in order, writing results as it goes so the report fills in progressively.

**Stage 1 — resolve and clone.** Resolve the repository's canonical `nameWithOwner` *before* anything
else, and store both the requested and canonical slug. This is not a nicety: GitHub's search index is
keyed on a repository's current name while `repository(owner, name)` follows renames, so a renamed
repository otherwise reports zero PRs and looks successful. Phase 0 hit this on
`encode/starlette` → `Kludex/starlette`. Then clone with `--filter=blob:none --no-checkout`
(measured: 2.0 s / 5.1 s / 79.3 s for small / medium / huge; 1.9 / 14.7 / 254.8 MiB).

**Stage 2 — areas and activity, from the clone only.** Fit the area rule to the file tree, then read
commit history for area activity and contributor counts. No API calls at all, so this is the
progressive first result. Phase 0 measured `git log --name-only` at 0.09 s, 3.2 s and **224 s on
kubernetes**, most likely (estimated, not re-measured on kubernetes) because of git's rename
detection, which compares file contents and so makes a blobless clone download blobs on demand. On a
fresh blobless clone of `pallets/click` it did exactly that: 25 objects downloaded and under 0.1 s →
5.1 s (measured, `results/m2/rename_probe_click.txt`). With `--no-renames` (measured in
`results/m2/`), the same twelve months of kubernetes history reads in **0.6 s** on a fresh clone, and
no objects are downloaded. A rename then counts as a delete plus an add. The slow part of stage 2
on huge repositories is the clone itself (71.7 s for kubernetes), so the job's progress field still
says which stage it is in rather than promising a time.

Activity counts only non-merge, non-bot commits from the last 12 months by committer date, and a
commit counts once per area it touches. Root files and excluded directories (top-level names only)
count toward no area. **Sweep commits** — formatting, licence headers or mass renames — are ignored,
because they say nothing about where work happens. A sweep touches more than half of all areas *and*
at least five areas (both configurable); the minimum stops an ordinary "code + tests" commit in a
two- or three-area repository from counting as one. The number ignored is stored on the repo and
explained on the method page. The band uses only the brief's two windows, so it adds no thresholds:
**active** has a commit in the last 90 days, **steady** has commits in the last 12 months
but none in 90 days, **dormant** has none in 12 months. This stage stores counts only: commits and
distinct commit authors per area. Authors are identified by email to be counted and are never stored;
no mailmap is applied, so one person with two emails counts twice.
Named contributors and reviewers come from PR data in stage 4 (merged PRs authored and reviews
submitted, counts only), because git names do not map reliably to GitHub logins.

**Stage 3 — PR ingest.** Page `repository.pullRequests` newest-first at 50 per page with
`files(first: 100)` inline. Sampling is up to 250 PRs per calendar month across the 12-month window
(ADR-0004). Points cost 1–2 per page, so the file list is fetched inline rather than in a second pass
— a two-pass design would add complexity to save roughly one point per page. Any PR with more than 100
changed files needs its own follow-up requests; on kubernetes that was 83 PRs and 322 extra requests,
costing 313 s, the largest single stage in the whole analysis. A PR whose file list cannot be completed
is marked and excluded rather than silently truncated.

**Stage 4 — first-timer lookback and metrics.** For each distinct non-bot author, one `search` query
returns their earliest merged PR in the repository; a PR is a newcomer PR when no merged PR by that
author was created before it (ADR-0002). Twenty author searches are batched into one request using
GraphQL aliases, which took `optuna/optuna` from 148 requests to 8. Metrics are then pure functions
over stored rows.

Measured cold totals, including clone and git history: **81 s** small, **56 s** medium, **986 s**
(16.4 min) huge. Total API cost for all three repositories: **478 of 5,000** hourly points. The rate
limit is not a constraint; wall-clock is. Note that the small repository is slower than the medium one,
because cost tracks PR count and author diversity rather than repository size — `Kludex/starlette` has
254 distinct authors to optuna's 148.

## 4. Data model

Five tables, no ORM.

- `repos` — requested slug, canonical slug, default branch, the fitted area rule, the excluded-directory
  list, snapshot time, and the sampling record (total PRs, sampled PRs, per-month counts, whether capped).
- `prs` — one row per sampled PR: number, author login, `author_is_bot`, `author_association` (stored for
  the method page, never used to decide), created/merged/closed times, state, `changed_files`,
  `files_complete`, `is_newcomer`, `first_formal_review_at`, `first_human_response_at`.
- `pr_areas` — `(repo_id, pr_number, area, file_count)`, keyed on `(repo_id, pr_number, area)`. A PR
  counts toward the area holding most of its changed files; ties count for each tied area, so this is
  many-to-many by design.
- `area_stats` — the computed output per area: mature newcomer PR count, merged count, merge rate, Wilson
  bounds, band, distinct newcomer authors, top author's share and the concentration flag, stale-open
  count, median hours to first formal review and first human response, commit counts, distinct commit
  authors, activity band, and the top contributors and reviewers as small `[{login, count}]` JSON lists,
  which keeps people counts inside the five tables.
- `jobs` — state, current stage, progress, a checkpoint blob, attempt count, last error.

Development runs against a local PostgreSQL 18 server; any Postgres reachable through `DATABASE_URL`
works, and Neon additionally needs `sslmode=require`. `init-db` uses `CREATE ... IF NOT EXISTS`, so it
is safe to re-run but does not alter an existing table. When the schema changes in v0, the tables are
dropped and `init-db` is run again: every row is derived from public data and is rebuilt by
re-analysing, which v0 does in full anyway (ADR-0007).

Both response timestamps are stored on every PR, because formal-review coverage ranged from 16.8% to
73.5% across the three reference repositories and kubernetes answers through comments roughly three
times faster than through submitted reviews. The report leads with formal review and falls back to
human response when a repository's formal-review coverage is below a configurable share.

## 5. The metric, precisely

- **Bots** excluded from PR authors, review authors and comment authors.
- **Newcomer PR**: no merged PR by this author created before this one, over all repository history.
- **Mature**: created at least 30 days before the snapshot and no longer open.
- **Merge rate** = merged / (merged + closed unmerged). Open PRs never enter the denominator.
- **Minimum sample**: 10 mature newcomer PRs per area, else "not enough data".
- **Repo rate**: the same merge rate computed across the whole repository.
- **Band**: compare the area's 95% Wilson interval with the repo rate — entirely above, entirely below,
  or overlapping.
- **Distinct newcomer authors** per area, shown beside the sample size: 12 PRs from 3 people is not 12
  PRs from 12, and the Wilson interval cannot tell the difference.
- **Author concentration flag** when one author holds more than 30% of an area's mature newcomer PRs.
  At n=12 that is four PRs from one person, so the flag fires often at these sample sizes — which is
  the point: it says the merge rate is describing an individual's experience, not the area's.
- **Stale open**: newcomer PRs still open after 90 days. They are deliberately outside the merge rate,
  which counts only merged and closed-unmerged PRs. Without this count, an area that never acts on
  newcomer PRs is indistinguishable from one with no backlog — the worst case for a newcomer looks
  identical to the best. Reported per area and explained on the method page.

On the reference set this yielded 4, 7 and 9 qualifying areas. Bands separate the extremes cleanly
(`optuna/visualization` 0.357–0.802 against `optuna/study` 0.062–0.335) and correctly refuse to
separate neighbours.

## 6. Failures

The worker assumes every long run will be interrupted, because the first long Phase 0 run was. GitHub
closed the connection mid-pagination and the measurement script lost two already-completed repositories
because it only saved at the end.

- Retry the **whole transport exception group** with exponential backoff. `RemoteDisconnected`
  subclasses `ConnectionResetError` and `HTTPException` but **not** `urllib.error.URLError`, so a
  handler catching only `URLError` lets it through — which is exactly what happened.
- Checkpoint after every page and every stage, into `jobs.checkpoint`, so a resumed job continues
  instead of restarting. A 16-minute job that restarts from zero on a dropped connection is not viable.
- Track `rateLimit` on every response and stop cleanly before exhaustion rather than failing mid-write.
- A job that fails permanently leaves its partial results and records `last_error`; the report then
  renders what exists with an explicit incomplete note.

## 7. Deliberately not here

No Celery, Redis, ORM, microservices, LLM or embeddings. No API hosting in v0 — "paste any URL" is
local-only, since Phase 0 found Spaces now needs a paid plan and Actions cannot serve HTTP. Starter
issues and ownership are both cut from v0 and live in stretch, because the open starter-issue backlog
was empty on two of three reference repositories and CODEOWNERS covered zero contribution areas.
Nobody is called a maintainer or owner anywhere in v0, because v0 ships no ownership data.

## 8. Open risks

- **The bands' predictive value is unproven.** Everything above describes a snapshot. Whether a band
  of "above repo average" before a cutoff predicts anything after it is the M6 validation, and it has
  not been run. With intervals this wide a null result is realistic and will be reported as such.
- **Sampling changes what the window means.** Monthly caps keep the window honest but make per-month
  counts load-bearing on the report.
- **Huge repositories are dominated by two stages**: the clone (71.7 s for kubernetes) and 313 s of
  files pagination. The Phase 0 cold totals above include 224 s of `git log`, estimated to be mostly
  blob fetching for rename detection, which `--no-renames` removes. The M6 performance run will
  re-measure the totals.
- **The first-timer lookback cannot see pre-GitHub or non-PR contributions**, so someone who contributed
  only by direct push counts as a newcomer. Stated on the method page.

Decisions are recorded individually in `docs/decisions/`.
