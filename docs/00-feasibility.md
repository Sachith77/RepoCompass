# Phase 0 feasibility report

Snapshot date: 2026-11-03. Every figure is labelled **measured** or **estimated**. Measured figures
come from scripts run against the live GitHub API and local clones on that date; raw output is in
`results/phase0/`. Nothing in this document is a target.

Companion document: `docs/data/github_signals.md` covers the signal definitions in detail
(checklist items 4, 5, 6 and 7).

---

## Decisions after Phase 0

Taken on 2026-11-03 in response to the findings below, and already applied to `docs/BRIEF.md`.

| # | decision | driven by |
|---|---|---|
| 1 | Python 3.14 in a project `venv` at `.venv`, no conda. CI uses 3.14 too. | section 8: 3.11 and conda are absent, and the full stack installs on 3.14 with prebuilt wheels |
| 2 | **Starter issues cut from v0**, moved to stretch along with the availability evaluation. `starter_issues` dropped from the tables. | section 4 and signals section 5: zero open labelled issues on 2 of 3 repos |
| 3 | **Ownership cut from v0.** CODEOWNERS and Kubernetes-style `OWNERS` parsing moved to stretch. Vendored and generated directories excluded from areas entirely, via a configurable list. | signals section 7: CODEOWNERS covers zero contribution areas; `vendor/` held decoy CODEOWNERS files |
| 4 | **Bands, not positions.** Each area's 95% Wilson interval is compared with the repo-wide mature newcomer merge rate and labelled above / below / no clear difference. Validation asks whether areas banded "above" before the cutoff stay above the repo rate after it. | section 5: adjacent intervals overlap almost completely at n=12–20 |
| 5 | **Sampling changed** from "most recent 3,000 PRs" to up to 250 PRs per calendar month across the window. Total, sampled and per-month counts recorded; report labelled "sampled" when capped. | section 5: the flat cap left kubernetes with 134 days and called it 12 months |
| 6 | Queue and worker confirmed. Progressive results retained. | section 6: 81 s, 56 s and 16.4 min cold, plus a real mid-run connection drop |
| 7 | **No API hosting in v0.** "Paste any URL" is local-only. Stretch option is exporting pre-analyzed reports as static pages for Vercel. | section 7: Spaces now needs a paid plan and Actions cannot serve HTTP |
| 8 | Postgres on Neon; `DATABASE_URL` supplied out of band and never read or printed. | section 7: Neon auto-resumes, Supabase needs a manual unpause |

The three reference repositories are unchanged: `Kludex/starlette`, `optuna/optuna`,
`kubernetes/kubernetes`.

Two items from section 10 remain open and are resolved in Phase 1 rather than here: how `(root file)`
should be treated now that it would appear as a band entry, and whether the incremental refresh CLI is
worth building. Both are design decisions with an ADR each.

---

## Verdict

The core idea is feasible. Ranking areas by newcomer merge rate produced 4, 7 and 9 qualifying areas
on the three test repositories, and the ranking separates at the extremes. The whole pipeline is
cheap in API terms: all three repositories together cost 478 of 5,000 hourly points.

Five things found during Phase 0 contradict assumptions written into `docs/BRIEF.md` and must be
resolved in Phase 1:

1. **The starter-issues feature has almost nothing to show.** Two of the three test repositories have
   zero open issues carrying newcomer labels. This is not a bug and not a sampling artefact; well
   maintained projects triage that backlog to zero.
2. **CODEOWNERS supplies owner evidence for zero contribution areas** across all three repositories.
3. **A strict 1-2-3 ranking overstates the data.** At the sample sizes available, the 95% intervals
   of adjacent areas overlap almost completely. Top versus bottom separates cleanly; neighbours do
   not. Report bands, not positions.
4. **Kubernetes' "12-month window" is really 134 days** once the 3,000-PR cap applies — 37% of the
   intended window. The sample note must print real dates.
5. **Hugging Face Spaces is no longer a free host for this API.** Docker and Gradio Spaces now
   require a paid plan.

The rate limit is a non-issue. Wall-clock time is the only real cost, and it exceeds the brief's
60-second threshold on two of three repositories, so the queue and worker should be built.

---

## 1. Test repositories (item 1)

| role | repository | why |
|---|---|---|
| small | `Kludex/starlette` | small codebase, genuinely active, 63 commit authors in 12 months |
| medium | `optuna/optuna` | `src/<pkg>`-style layout that exercises a deeper area rule |
| huge | `kubernetes/kubernetes` | stresses the cap, pagination, and the area rule |
| dormant control | `encode/httpx` | 3 commits in 12 months, 0 in the last 3 — shows the empty-data path |

`encode/httpx` was originally chosen as the small repository. Measurement showed it has **3 commits
in 12 months and 0 in the last 3** (measured), so it is dormant rather than small, and would have
produced no newcomer data. It was replaced by `Kludex/starlette` and kept as a deliberate control.

Candidate screening data for the replacement is in `results/phase0/small_repo_screen.json`.

Note that `Kludex/starlette` is reached as `encode/starlette`; see the rename finding in
`docs/data/github_signals.md` section 1.

---

## 2. Clone cost (item 2)

`git clone --filter=blob:none --no-checkout`, then `git log --since='12 months ago' --no-merges
--name-only`. All measured.

| repository | clone | on disk | commits (all time) | commits (12 mo, no merges) | changed-path rows (12 mo) | `git log --name-only` |
|---|---|---|---|---|---|---|
| `Kludex/starlette` | 2.0 s | 1.9 MiB | 1,800 | 261 | 593 | 0.09 s |
| `optuna/optuna` | 5.1 s | 14.7 MiB | 21,871 | 1,199 | 1,945 | 3.2 s |
| `kubernetes/kubernetes` | 79.3 s | 254.8 MiB | 142,942 | 5,816 | 47,686 | **224.0 s** |
| `encode/httpx` (control) | 2.6 s | 1.5 MiB | 1,523 | 3 | 5 | 0.08 s |

Blobless no-checkout clones are cheap in disk and in time, and cost zero API points. The surprise is
that **`git log --name-only` on kubernetes takes 224 seconds** — longer than the clone itself, and the
single slowest local step in the whole pipeline. It is tree-diffing 5,816 commits across a very large
tree.

Consequence for the design: the "areas map first" progressive result is fast for small and medium
repositories (under 6 seconds end to end for `optuna/optuna`) but takes about five minutes for
kubernetes. Phase 1 should treat commit-based area activity on huge repositories as a slow stage, not
a quick first result. Reducing that cost is an optimisation worth an ADR, not a correctness issue.

Source: `results/phase0/clone_cost.json`.

---

## 3. GraphQL cost (item 3)

Three query shapes were timed over three pages each, on every repository, reading the API's own
`rateLimit.cost` field. All measured.

| page size | files connection | points per page | seconds per page (range across repos) |
|---|---|---|---|
| 25 | `files(first: 100)` | **1** | 1.6 – 2.9 |
| 50 | `files(first: 100)` | **2** | 3.5 – 6.5 |
| 50 | none | **1** | 2.2 – 5.2 |

**The rate limit is not the constraint.** A complete medium-repo analysis cost **31 points** of the
5,000-per-hour budget (measured). By points alone one token could analyse roughly 161 medium
repositories per hour (estimated); by wall-clock it manages about 51 (estimated). Wall-clock is the
binding constraint by a factor of three.

Because the `files` connection costs only one extra point per page, there is **no reason to split
ingest into a cheap metadata pass and a second file pass**. Fetch files inline.

PR volume against the 3,000 cap (measured):

| repository | PRs created in last 12 months | over the cap? |
|---|---|---|
| `Kludex/starlette` | 560 | no |
| `optuna/optuna` | 526 | no |
| `kubernetes/kubernetes` | 6,616 | **yes, 3,616 dropped** |
| `encode/httpx` | 54 | no |

Only the huge repository hits the cap, and the effect is more severe than the raw count suggests: the
cap retains kubernetes PRs only from **2026-06-22**, which is **134 days, 37% of the intended
window** (measured). Its reports must carry the partial-sample note the brief requires, and must
print the real date range rather than claiming 12 months. See section 5.

**Files pagination is far more expensive than the point cost suggests.** Over the full window
(measured):

| repository | PRs truncated at 100 files | extra requests | time spent paginating files |
|---|---|---|---|
| `Kludex/starlette` | 3 | 11 | 8.7 s |
| `optuna/optuna` | 0 | 0 | 0.0 s |
| `kubernetes/kubernetes` | 83 | 322 | **313.4 s** |

For kubernetes this is the **single largest stage of the whole analysis** — larger than the PR ingest
itself — because each truncated PR needs its own sequential round trip. It costs almost nothing in
points and a great deal in wall-clock. Any PR whose file list cannot be completed must be marked and
excluded rather than silently truncated; in this run 0 PRs ended up incomplete after pagination.

Source: `results/phase0/graphql_cost.json`.

---

## 4. Signal definitions (items 4, 5, 6, 7)

Full detail, tables and decisions are in `docs/data/github_signals.md`. Summary of what was decided:

- **Repository identity.** Resolve `nameWithOwner` before any `search()` query. A renamed repository
  otherwise reports zero PRs and looks successful.
- **First-time contributor.** Use our own rule ("no merged PR by this author created before this
  one", over all repository history), not `authorAssociation`. The two disagreed on 9 of 60 sampled
  PRs, and 8 of those 9 were biased in the direction of the outcome being measured. The lookback
  costs one query per distinct author and batches 20 per request.
- **Response times.** Store both first formal review and first human response. Formal-review coverage
  ranges from 16.8% to 73.5% across the three repositories, and kubernetes answers through comments
  roughly three times faster than through submitted reviews.
- **Starter issues.** Keep the feature, demote it, and build a real empty state. See the verdict above.
- **Areas.** A fixed one-or-two-level rule does not fit kubernetes. An adaptive depth rule is adopted.
- **Ownership.** CODEOWNERS is usually absent or irrelevant; also parse per-directory `OWNERS` files
  and label which file the evidence came from.

---

## 5. Does the headline metric have enough data? (the central question)

Everything else is pointless if too few areas reach the brief's minimum of 10 mature newcomer PRs.
The full 12-month window was ingested for all three repositories and run through the real pipeline.
All measured.

| repository | PRs in window | non-bot | distinct authors | newcomer PRs | mature newcomer PRs | areas with any data | **areas clearing min sample 10** |
|---|---|---|---|---|---|---|---|
| `Kludex/starlette` | 560 | 510 | 254 | 302 | 207 | 5 | **4** |
| `optuna/optuna` | 526 | 517 | 148 | 168 | 141 | 28 | **7** |
| `kubernetes/kubernetes` | 3,000 (capped) | 2,998 | 746 | 735 | 313 | 38 | **9** |

**Answer: yes.** Every repository produces enough qualifying areas to rank, and the ranking separates
at the extremes. Ranked by Wilson lower bound, with the full 95% interval shown:

`optuna/optuna` (7 qualifying of 28):

| area | n | merge rate | 95% Wilson interval |
|---|---|---|---|
| `optuna/visualization` | 15 | 0.600 | 0.357 – 0.802 |
| `optuna/samplers` | 20 | 0.550 | 0.342 – 0.742 |
| `optuna/pruners` | 13 | 0.538 | 0.291 – 0.768 |
| `optuna/storages` | 12 | 0.417 | 0.193 – 0.681 |
| `optuna/trial` | 15 | 0.333 | 0.152 – 0.583 |
| `tests/study_tests` | 12 | 0.333 | 0.138 – 0.609 |
| `optuna/study` | 26 | 0.154 | 0.062 – 0.335 |

`kubernetes/kubernetes` (9 qualifying of 38): `test` (n=35, 0.571), `pkg` (n=117, 0.427),
`staging/src/k8s.io/api` (n=12, 0.583), `.../dynamic-resource-allocation` (n=19, 0.368),
`.../kubectl` (n=31, 0.323), `.../client-go` (n=16, 0.375), `.../apiserver` (n=17, 0.294),
`.../apimachinery` (n=13, 0.308), `(root file)` (n=12, 0.167).

`Kludex/starlette` (4 qualifying of 5): `docs` (n=44, 0.455), `starlette` (n=157, 0.178),
`(root file)` (n=14, 0.286), `tests` (n=142, 0.169).

Three caveats come straight out of these numbers, and all three affect how the report must be built.

**The intervals overlap too much to support a strict ordering.** At n=12–20 the intervals are roughly
0.4 wide. `optuna/visualization` (0.357–0.802), `optuna/samplers` (0.342–0.742) and `optuna/pruners`
(0.291–0.768) are statistically indistinguishable from each other. What *does* separate is top versus
bottom: `optuna/visualization` (0.357–0.802) against `optuna/study` (0.062–0.335) do not overlap, and
`docs` (0.317–0.599) against `tests` (0.116–0.239) do not overlap.

So ranking by Wilson lower bound is sound, but rendering it as a numbered 1-2-3 list would imply a
precision the data does not have. Phase 1 should group qualifying areas into a small number of
labelled bands rather than a strict order, while still printing every interval as the brief requires.
This reinforces the brief's existing rule that no copy may claim an area is objectively easiest.

**`(root file)` qualifies in two of three repositories** (n=14 and n=12). It is an artefact, not an
area: it collects `README.md`, `pyproject.toml` and similar. It must be excluded from ranked areas.

**Kubernetes' "12-month window" is really 134 days.** Measured: the 3,000-PR cap retains PRs created
on or after **2026-06-22**, which is 134 days, or **37% of the intended window**. After the 30-day
maturity rule, about 104 days remain usable. This is also why kubernetes keeps only 313 of its 735
newcomer PRs — the capped window is dominated by PRs too recent to have settled. The sample note must
print the real date range, because calling this "the last 12 months" would be false.

Sources: `results/phase0/area_sample_sizes.json`, `results/phase0/cap_window_span.json`.

---

## 6. Queue or synchronous? (item 8)

A complete analysis of the medium repository was run end to end against the live API and timed
(measured):

| stage | seconds |
|---|---|
| local git history (clone already present) | 0.08 |
| PR ingest, 11 pages of 50 with files inline | 45.59 |
| files pagination beyond 100 | 0.00 |
| first-timer lookback, 148 authors in 8 batched requests | 24.50 |
| **total excluding clone** | **70.68** |
| total including the 5.09 s clone | 75.77 (estimated sum) |

The full three-repository run then measured every stage at window scale:

| stage | `Kludex/starlette` | `optuna/optuna` | `kubernetes/kubernetes` |
|---|---|---|---|
| PR ingest | 35.8 s | 27.7 s | 260.0 s |
| files pagination | 8.7 s | 0.0 s | 313.4 s |
| first-timer lookback | 34.9 s | 20.4 s | 109.2 s |
| **total excluding clone** | **79.3 s** | **48.0 s** | **682.7 s** |
| plus clone and `git log` | +2.1 s | +8.3 s | **+303.3 s** |
| **full analysis from cold** | **~81 s** | **~56 s** | **~986 s (16.4 min)** |

Total API cost for all three repositories combined: **478 requests, 478 points** of the 5,000/hour
budget (measured). The rate limit was never close to binding.

**Decision: build the jobs table and the worker.** Three independent reasons:

1. The brief's own threshold is "under about 60 seconds, run it synchronously". Two of the three
   repositories exceed it from cold: 81 s for the *small* repository and **16.4 minutes** for the
   huge one. Only `optuna/optuna` comes in under, at 56 s, and that is close enough to the line that
   a slower network would cross it. A request-response cycle cannot hold a connection for that long.

   Note the ordering: the **small repository is slower than the medium one**. Analysis cost tracks PR
   count and author diversity, not repository size. `Kludex/starlette` has 254 distinct authors
   across 510 non-bot PRs, against 148 authors across 517 for `optuna/optuna` — so it needs 13
   lookback batches where optuna needs 8. Repository size is a poor predictor of analysis time;
   plan capacity on PR and author counts instead.
2. **Resumability is required, not optional.** The first attempt at the full three-repository run
   died on kubernetes with `http.client.RemoteDisconnected` — GitHub closed the connection during
   sustained pagination. Because that script only wrote its output at the end, a single dropped
   connection discarded the two completed repositories as well. This is exactly the failure the
   brief's "checkpoints so an interrupted run resumes" clause anticipates, and it happened on the
   first long run.
3. Progressive results are genuinely useful here, because the area map comes from the clone and needs
   no API calls at all.

A retry detail worth recording: `http.client.RemoteDisconnected` subclasses `ConnectionResetError`
and `HTTPException` but **not** `urllib.error.URLError`, so a retry handler that only catches
`URLError` lets it through. Catch the transport exception group explicitly.

Source: `results/phase0/end_to_end_medium.json`.

---

## 7. Hosting and storage (item 9)

All limits below were read from vendor documentation on 2026-11-03.

### Worker and API hosting

| | Hugging Face Spaces (free) | GitHub Actions (public repo) |
|---|---|---|
| compute | CPU Basic: 2 vCPU, 16 GB RAM | `ubuntu-latest`: 4 CPU, 16 GB RAM |
| disk | 50 GB, not persistent | 14 GB SSD |
| cost | CPU Basic hardware is free, **but creating a Docker or Gradio Space requires a paid plan** | free for standard runners on public repositories |
| job limit | sleeps when unused on free hardware | 6 h per job, 20 concurrent jobs on Free |
| scheduling | n/a | cron minimum interval 5 min; scheduled workflows auto-disabled after **60 days** of repository inactivity |
| can serve an HTTP API? | yes, if paid | **no** — batch only |

**This breaks a stretch item as written.** `docs/BRIEF.md` offers "API on Hugging Face Spaces or a
GitHub Actions worker". Spaces now requires a paid plan for Docker/Gradio, and Actions cannot serve an
HTTP API at all — it can only run the ingest as a batch job. So neither listed option hosts the API
for free. GitHub Actions remains a good fit for the *nightly refresh* stretch item, with 14 GB of disk
comfortably covering even kubernetes' 254.8 MiB clone.

If deployment is approved later, the API host needs to be chosen and verified then. I have not
verified any alternative provider's current free tier, so I am not naming one here.

### Database

Estimated size per analysed repository, derived from measured row counts and typical Postgres row
overhead including indexes. **Estimated, not measured** — no schema has been created yet.

| table | rows (medium, measured) | rows (huge, measured) | bytes/row (estimated) |
|---|---|---|---|
| `prs` | 526 | 3,000 (capped) | ~250 |
| `pr_areas` | ~630 | ~3,900 | ~120 |
| `area_stats` | 32 | 50 | ~250 |
| `starter_issues` | 0 | 147 | ~500 |
| **total** | **~0.25 MB** | **~1.3 MB** | |

| | Neon free | Supabase free |
|---|---|---|
| database size | 1 GB per project, 20 GB per account | 500 MB per project |
| projects | up to 100 | 2 active |
| egress | 5 GB/project/month | 5 GB |
| inactivity | compute **auto-suspends after 5 min** and resumes on connection; cannot be disabled | project **paused after 1 week**, requires **manual** unpause |
| backups | — | none on free |

Storage is not a constraint for either: at roughly 0.25–1.3 MB per repository, 500 MB holds hundreds
of analysed repositories (estimated).

**Recommendation: Neon.** The deciding factor is the inactivity behaviour, not size. Neon's suspend
resumes automatically on the next connection, costing only a cold start. Supabase pauses a free
project after a week and needs a manual unpause, which for a project that gets demonstrated
occasionally means it is reliably broken exactly when someone opens it.

Sources: Neon and Supabase pricing pages, Hugging Face Spaces overview, GitHub Actions limits and
runner reference, all read 2026-11-03.

---

## 8. Local setup on this machine (item 10)

| check | result |
|---|---|
| Python | **3.14.0 only.** No conda, no `uv`, no `py -3.11` available |
| project stack on 3.14 | **installs and imports cleanly**, all prebuilt wheels, no compiler needed |
| versions installed | fastapi 0.162.0, psycopg 3.3.7, httpx 0.28.1, scipy 1.18.1, pytest 9.2.0, ruff 0.17.3 |
| scipy functions needed | `spearmanr` and `bootstrap` both import and run |
| Docker Desktop | installed, version 29.1.3, currently **paused**; CLI responds, so Postgres is available after `docker desktop resume` |
| disk | 519.7 GB free on `D:` |

Two environment decisions are still open:

**Python version.** The project rules target Python 3.11 in a conda environment. This machine has
neither, and the measurement shows 3.11 is not needed — the full stack installs on 3.14 with
prebuilt wheels and no compiler. The options are to install Miniforge and create a 3.11 environment,
or to target 3.14 with a plain `venv` and install no extra tooling. The evidence favours the second.

**Postgres for development.** Docker Desktop is available, so a local container works once resumed.
If running Docker is unwanted, the Neon free tier is the fallback recommended above.

---

## 9. What this means for `docs/BRIEF.md`

Provisional architecture choices, now decided by measurement:

- **Jobs table and worker: build it.** Measured 70.68 s for a medium repository, over the brief's own
  60 s threshold, plus a demonstrated need for resumability.
- **Refresh CLI: still worthwhile**, and GitHub Actions is a suitable free host for it on a public
  repository, subject to the 60-day inactivity rule.
- **Fetch PR files inline.** The `files` connection costs one extra point per page, so a two-pass
  design would add complexity for no saving.

Statements in the brief that the evidence contradicts, for Phase 1 to resolve:

| brief says | measurement says |
|---|---|
| starter issues are a top-level report section | 0 open labelled issues on 2 of 3 repos; kubernetes' 6 open `good first issue` are all assigned |
| "CODEOWNERS owners if the repo has that file" | usable for 0 contribution areas on all 3 repos; kubernetes uses 593 `OWNERS` files instead |
| area rule is "one or two directory levels" | two levels leaves kubernetes with one area holding 64.8% of files; needs adaptive depth |
| "areas ranked by the lower bound" | correct statistic, but adjacent intervals overlap almost entirely at n=12–20; present bands, not an ordered list |
| "window: PRs created in the last 12 months" | true for 2 of 3 repos; for kubernetes the cap reduces it to 134 days from 2026-06-22 |
| "total PRs in the 12-month window … and the date range covered" | the date range is not a nicety here, it is the only honest label for a capped repo |
| deploy API on Hugging Face Spaces | now requires a paid plan |
| claim comments match prose phrases | kubernetes claims are overwhelmingly the `/assign` bot command |
| area of a PR = "the area with the most changed files" | works, but `(root file)` then qualifies as a rankable area on 2 of 3 repos; needs excluding |

---

## 10. Open risks and TODOs

- **TODO: availability evaluation needs more repositories.** The brief asks for 30–50 manually
  labelled starter issues. Only 147 open labelled issues exist across the three test repositories and
  141 of them are kubernetes `help wanted`, so the evaluation as specified would effectively measure
  one repository. Widen the repository set before running it.
- **`(root file)` is leaking into rankings as an area.** It qualified on two of three repositories
  (`Kludex/starlette` n=14, `kubernetes/kubernetes` n=12). `README.md` and `pyproject.toml` are not a
  place a newcomer "starts". Exclude root files from ranked areas in Phase 1, or group them as a
  clearly labelled non-area.
- **The ranking's predictive value is still unproven.** Everything in section 5 is a single-snapshot
  description. Whether a high Wilson lower bound before a cutoff predicts newcomer success after it
  is the validation in M7, and it has not been run. Phase 0 shows the metric is *computable*, not
  that it is *useful*. With intervals this wide, a weak or null validation result is a realistic
  outcome and must be reported honestly if it happens.
- **Files pagination is the dominant cost on huge repositories** — 313 s of kubernetes' 683 s, from
  83 PRs needing 322 extra sequential requests. If huge repositories matter, this is the first thing
  to parallelise, and it is a stage where a resumable checkpoint pays for itself.
- **The first-timer lookback cannot see pre-GitHub or non-PR contributions.** Someone who contributed
  only by direct push counts as a newcomer. Must be stated on the method page.
- **The 3,000 cap discards 3,616 of kubernetes' 6,616 window PRs**, leaving 134 days from 2026-06-22
  (measured) and about 104 usable days after the maturity rule. The partial-sample note is
  load-bearing, not decoration. Phase 1 should also decide whether the cap is the right lever at all,
  since for kubernetes it silently changes what "12 months" means.
- **`git log --name-only` at 224 s on kubernetes** is the slowest local stage and worth optimising if
  huge repositories matter.
- Starter-issue claim detection has not been validated for precision or recall yet; that is the
  evaluation in the brief, not a Phase 0 result.
