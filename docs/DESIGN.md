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
pages. The API (FastAPI under uvicorn, bound to 127.0.0.1) never calls GitHub; it only reads Postgres
and enqueues jobs, so every slow or failure-prone thing lives in the worker (ADR-0005). `POST
/analyze` returns the stored report if there is one; otherwise it queues a job — never two for one
requested name (an advisory lock on the name) — and re-queues a failed job whose snapshot is under 24
hours old so it resumes from its checkpoint. The worker claims the oldest queued job with `FOR UPDATE
SKIP LOCKED`. At start and whenever idle it re-queues running jobs with no checkpoint for 10 minutes:
a live job checkpoints every few seconds, minutes at most, so such a job was abandoned. `resume`
refuses a job that is running.

## 3. Pipeline

The worker runs four stages in order, checkpointing as it goes. `GET /jobs/{id}` shows the areas map
as soon as stage 2 is done; the full report appears when the final transaction commits.

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
no objects are downloaded. A rename then counts as a delete plus an add. On huge repositories
the slow part of stage 2 is the clone itself (71.7 s for kubernetes).

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
`files(first: 100)` inline. Bot PRs are counted and dropped first, then up to 250 human PRs per
calendar month are kept (ADR-0004); paging is newest-first, so a capped month keeps its newest 250.
Pages cost 1–2 points, so files are fetched inline. Each kept PR is reduced to per-area file counts,
response times and reviewers — no paths are kept. Any PR with more than 100
changed files needs its own follow-up requests; on kubernetes that was 83 PRs and 322 extra requests,
costing 313 s, the largest single stage in the whole analysis. A PR whose file list cannot be completed
— including one longer than GitHub's 3,000-file listing — is marked and excluded, never truncated.

**Stage 4 — first-timer lookback and metrics.** For each distinct non-bot author, one `search` query
returns their earliest merged PR in the repository; a PR is a newcomer PR when no merged PR by that
author was created before it (ADR-0002). Twenty author searches are batched into one request using
GraphQL aliases, which took `optuna/optuna` from 148 requests to 8. Metrics are then pure functions
over the PR records. Only then are all of the repository's rows replaced, in one transaction
(ADR-0008); until that point the job checkpoint holds everything, including the areas map.

Measured in M4 through the API and worker, clones already on disk (`results/m4/run1/`): the areas map
within 6 s, full analysis **120 s** small, **96 s** medium, **2,080 s** (34.7 min) huge, using 49, 31
and 606 of 5,000 hourly points. Wall-clock is the constraint: kubernetes pages all 6,619 human PRs
(1,895 s) to count every month.

## 4. Data model

Five tables, no ORM.

- `repos` — requested slug, canonical slug, default branch, the fitted area rule, the excluded-directory
  list, snapshot time, and the sampling record (total PRs, sampled PRs, per-month counts, whether capped).
- `prs` — one row per sampled human PR: number, author login, `author_association` (stored for
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

Development runs against a local PostgreSQL 18 server (Neon also works, with `sslmode=require`).
`init-db` is safe to re-run but does not alter an existing table, so when the schema changes in v0 the
tables are dropped and re-created: every row is derived from public data and rebuilt by re-analysing.

Both response timestamps are stored, because formal-review coverage ranged from 16.8% to 73.5% across
the reference repositories. The report leads with formal review and falls back to human response when
a repository's coverage is below a configurable share.

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
- **Author concentration flag** when one author holds more than 30% of an area's mature newcomer PRs:
  the merge rate then describes one person's experience more than the area's.
- **Stale open**: newcomer PRs still open more than 90 days. They are deliberately outside the merge
  rate, which counts only merged and closed-unmerged PRs. Without this count, an area that never acts
  on newcomer PRs is indistinguishable from one with no backlog.
- **Response**: the median time to a response, over newcomer PRs that got one (with that count), and
  the share of mature newcomer PRs with no human response within 30 days. The median alone hides PRs
  nobody answered; the share alone hides how slow answers are. Only the first 20 reviews and 30
  comments per PR are read; a PR whose slice holds no human answer but has more is marked unknown.

On the reference set this yielded 4, 7 and 9 qualifying areas. Bands separate the extremes cleanly
(`optuna/visualization` 0.357–0.802 against `optuna/study` 0.062–0.335) and correctly refuse to
separate neighbours.

## 6. Failures

Every long run is assumed to be interrupted: the first long Phase 0 run lost two finished repositories
when GitHub closed the connection, because the script saved only at the end.

- Retry the **whole transport exception group** (`httpx.TransportError`, which includes a server
  closing the connection) plus 502/503/504 and secondary rate limits, with exponential backoff. The
  Phase 0 script caught only `URLError`, which `RemoteDisconnected` is not — exactly what failed.
- Checkpoint after every page and every stage, into `jobs.checkpoint`, so a resumed job continues
  instead of restarting.
- Track `rateLimit` on every response and stop cleanly before exhaustion rather than failing mid-write.
- A failed job keeps its checkpoint and records `last_error`. The repository's previous complete report,
  if any, is untouched, because rows are only replaced when a run finishes (ADR-0008). If the database
  fails between saving and marking the job done, the job is re-run later; the save is idempotent.

## 7. Deliberately not here

No Celery, Redis, ORM, microservices, LLM or embeddings. No API hosting in v0: "paste any URL" is
local-only (Spaces now needs a paid plan). Starter issues and ownership are stretch items: the open
starter-issue backlog was empty on two of three reference repositories and CODEOWNERS covered zero
areas. Nobody is called a maintainer or owner, because v0 ships no ownership data.

## 8. Open risks

- **The bands' predictive value is unproven** until the M6 cutoff validation. With intervals this wide
  a null result is realistic and will be reported as such.
- **Sampling**: a capped month keeps its newest 250 PRs, so per-month counts matter on the report.
- **Worker memory is unmeasured.** A run was stopped by the machine running low on memory.
  TODO: measure the worker's peak memory on kubernetes before relying on it.
- **Huge repositories are slow**: 34.7 min for kubernetes, almost all PR pages, plus 71.7 s for a cold
  clone. M6 re-measures cold totals.
- **The first-timer lookback sees only PRs**: someone who contributed by direct push counts as a
  newcomer (ADR-0002).

Decisions are recorded individually in `docs/decisions/`.
