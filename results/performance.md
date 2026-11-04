# Performance

Collected from the measured runs in `results/`; every number below is measured on this machine (Windows,
local PostgreSQL 18, the live GitHub API, one shared token with a limit of 5,000 points an hour, per
`phase0/graphql_cost.json`) and cites its file. The two sentences marked "reasoned" are inferences from
these numbers, not measurements.

## Full analyses through the API, queue and worker

From `m4/run1/full_runs.txt` (2026-11-03). Clones were already on disk, so the git stage is a fetch, not
a clone. Times are from the job starting to run, polled every 2 s.

| repository | size | areas map shown after | full analysis | git stage | PR pages | first-timer lookback | API |
|---|---|---|---|---|---|---|---|
| Kludex/starlette | small | 2 s | 120 s | 2.7 s | 71.8 s | 45.8 s | 37 requests, 49 points |
| optuna/optuna | medium | 2 s | 96 s | 1.8 s | 69.0 s | 24.5 s | 20 requests, 31 points |
| kubernetes/kubernetes | huge | 6 s | 2,080 s | 5.3 s | 1,895.2 s | 177.1 s | 473 requests, 606 points |

The areas map is the progressive first result: it is ready after the git stage, while the PR stages run.
On kubernetes nearly all the time is PR pages: monthly sampling has to page through all 6,619 human PRs
in the window to count every month, even though it keeps 3,082.

## Repeat runs

| run | repository | full analysis | API | file |
|---|---|---|---|---|
| run 2, worker | Kludex/starlette | 126.1 s | 37 requests, 49 points | `m4/run2_worker_log.txt` |
| run 2, worker | optuna/optuna | 90.3 s | 20 requests, 31 points | `m4/run2_worker_log.txt` |
| `analyze` command | Kludex/starlette | 123 s wall | 37 requests, 49 points | `m3/analyze_starlette.txt` |
| `analyze` command | sqlfluff/sqlfluff (medium) | 219.2 s wall | 48 requests, 75 points | `m6/analyze_sqlfluff.txt` |

sqlfluff's stages: git 2.5 s, PR pages 162.5 s, lookback 52.3 s; 1,179 human PRs, sampled (at least
one month capped).

## Resume after an interruption

From `m4/resume_test.md` (2026-11-04): kubernetes, stopped at about 30% of its PR pages and resumed from
its checkpoint. The resumed session took 1,059.6 s; the job's total cost was 473 requests and 606 points,
the same as the uninterrupted run 1 (reasoned from the equal totals: no page was fetched twice).
The worker's peak working set was 72 MB, and free system memory never fell below 1,635 MB.

## Clones and git history

| measure | value | file |
|---|---|---|
| cold blobless clone, kubernetes | 71.7 s | `m2/cold_git_log_kubernetes.txt` |
| 12 months of git history on that fresh clone, with `--no-renames` | 0.6 s, no objects downloaded | `m2/cold_git_log_kubernetes.txt` |
| cold blobless clone, Phase 0 (small httpx / medium optuna / huge kubernetes) | 2.63 s / 5.09 s / 79.29 s | `phase0/clone_cost.json` |

## Rate limit

The largest analysis, kubernetes, used 606 of the 5,000 points available per hour. Reasoned from that:
the rate limit is not the constraint; wall-clock time is.
