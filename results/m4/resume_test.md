# Resume test: kubernetes/kubernetes from a 30% checkpoint

Run 2026-11-04 on this machine (local PostgreSQL 18, live GitHub API, clone already on disk).
All values are measured unless marked otherwise. Raw files are in `resume_test/`.

## Setup

Job 11 (kubernetes/kubernetes) had stopped on 2026-11-03 when the machine ran low on memory, about 30%
through its PR pages, and was marked failed with its checkpoint kept (see `run2_worker_log.txt`).
State before this test, read from the jobs table at 05:36 UTC:

| field | value |
|---|---|
| state, stage, progress, attempts | failed, prs, 30, 1 |
| checkpoint snapshot | 2026-11-03T16:14:15Z (13.4 h earlier, inside the 24 h resume window) |
| PRs already in the checkpoint | 1,085 |
| usage in the checkpoint | 151 requests, 201 points; pr_pages 512.1 s, git_stage 5.1 s |

Steps: `enqueue_job(…, "kubernetes/kubernetes")` (the call `POST /analyze` makes) at 05:36:55 UTC,
then `python -m repocompass worker --once` from 05:37:11 to 05:54:52 UTC. Memory and job progress
were sampled while it ran (memory every 5 s, job row about every 70 s).

Stop rule, chosen before the run: stop the worker if free system memory fell below 400 MB or the
worker's working set passed 1,500 MB. It was never reached.

## It resumed, it did not restart

- Re-submitting returned job 11 itself, `queued` (not a new job).
- The worker log says `job 11: kubernetes/kubernetes started`; the job finished with attempts = 2.
- The snapshot stayed 2026-11-03T16:14:15Z, so the git stage did not run again.
- The first progress sample after the claim (05:37:22) showed 1,085 PRs and 152 requests: the
  checkpoint's 1,085 PRs and 151 requests plus one new page. A restart would have begun at 0 PRs.
- The job's final usage is 473 requests and 606 points, the same totals as run 1, which ran without
  interruption (`run1/full_runs.txt`). A restart would have spent the first 151 requests again.

## Timing

| measure | value |
|---|---|
| resumed session, claim to done (worker log) | 1,059.6 s (17.7 min) |
| job usage recorded across both sessions | git_stage 5.1 s, pr_pages 1,432.7 s, lookback 137.6 s |
| PR pages in this session | from 30% to done |

The stage seconds add both sessions' recorded time, but not the minutes of the first session between its
last checkpoint and the stop, which were never saved. So they are not a clean single-run total; run 1's
2,080 s remains the uninterrupted figure.

## Memory

| measure | value |
|---|---|
| worker interpreter, peak working set (Windows PeakWorkingSet64, highest sample) | 72 MB |
| worker interpreter, highest private bytes sample | 57 MB |
| venv launcher process | 4 MB |
| lowest free system memory during the run | 1,635 MB of 15,989 MB |
| samples | 179 per process, 05:37:21 to 05:54:47 UTC |

The last sample is 5 s before the worker exited, so the final save transaction (writing the rows) is
not covered by a sample. The checkpoint at the end was 322,200 bytes stored, with 3,085 PRs.

Reading: at 72 MB, the worker's own memory is small at kubernetes scale, and keeping the checkpoint in
memory and re-saving it after every page did not make it grow large. What filled the machine's memory
on 2026-11-03 was not measured; the worker is unlikely to have been the cause (reasoned, not measured).

## Result

| field | value |
|---|---|
| human PRs in window / bot or non-user dropped / kept | 6,619 / 3 / 3,085 (sampled) |
| PRs with incomplete file lists / unknown response times | 5 / 2 |
| repo rate | 0.336 over 532 mature newcomer PRs |
| formal-review coverage | 0.597, so the report leads with formal review |
| above repo average | staging/src/k8s.io/apiserver, n=22, [0.347, 0.731] |
| below repo average | staging/src/k8s.io/apimachinery, n=22, [0.025, 0.278] |
| no clear difference | 8 areas; 39 areas not enough data |

Run 1 kept 3,082 PRs; this job's snapshot is 2026-11-03T16:14:15Z rather than run 1's, so the window
edges differ slightly. The banded areas and their intervals match run 1.
