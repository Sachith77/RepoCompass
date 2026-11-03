# RepoCompass: know a repo before you contribute
Paste a public GitHub repo URL and get an answer to: "If I want to contribute here, where might I start?"
Built from the repo's git history and PR/review data, which a code-reading tool cannot see.
Every number is computed from public data, shown with its sample size, and validated against what really happened.

Decisions recorded after Phase 0 are in docs/00-feasibility.md, section "Decisions after Phase 0".

## v0 report (in this order)
1. Where to start. Heading: "Based on historical contribution patterns, these areas may be better starting
   points." Each qualifying area is banded by comparing its 95% Wilson interval for the mature newcomer
   merge rate against the repo-wide mature newcomer merge rate:
   - interval entirely above the repo rate: "above repo average"
   - interval entirely below the repo rate: "below repo average"
   - interval overlapping the repo rate: "no clear difference"
   Each area shows merge rate, sample size, the interval, its band, the number of distinct newcomer
   authors, a "stale open" count, median time to first formal review, and links to example merged
   newcomer PRs. An area is flagged when a single author accounts for more than 30% of its mature
   newcomer PRs, because the merge rate then describes one person's experience more than the area's.
   Areas under the minimum sample are listed separately as "not enough data". No single opaque score,
   no 1-2-3 ranking, no implied ordering inside a band.
2. Areas map: each area with activity (commits in the last 90 days and 12 months, banded active / steady /
   dormant) and key contributors and reviewers (merged PRs authored and reviews submitted, counts only).
3. Sample note: total PRs in the 12-month window, how many were sampled, the per-month counts, whether any
   month was capped, and the date range actually covered. A capped window shows a clear "sampled" note and
   is never presented as complete.
4. Method page: plain-English definitions of every metric, the window and sample used, validation results,
   and what else affects merge rates (contributor experience, PR complexity, maintainer availability,
   release cycles, contribution guidelines). Never claim an area is objectively easiest.

## Definitions (implement exactly; each needs tests)
- Window: PRs created in the last 12 months. Sampling: up to 250 PRs per calendar month across the window.
  Record total PRs, sampled PRs and per-month counts per report; label the report "sampled" when any month
  was capped.
- Bots: excluded everywhere (logins ending in [bot] plus a configurable list, e.g. dependabot, renovate).
  The filter applies to PR authors, review authors and comment authors alike.
- Excluded directories: vendored and generated trees are excluded from areas entirely (e.g. vendor,
  third_party, node_modules). The list is configurable per repo and is shown on the report.
- Area of a file: its top-level directory; for layouts like src/<pkg>/ or pkg/, use more levels.
  Configurable per repo. The rule is shown on the report.
- Area of a PR: the area with the most changed files; ties count for each tied area. All changed files must be
  fetched (paginate the files connection beyond 100); if a PR cannot be fully fetched, mark it and exclude it.
- First-time contributor: no merged PR by this author in this repository was created before this one,
  checked over all available PR history of the repo, not just the window. Decided in Phase 0 against
  GitHub's authorAssociation; the limitation is documented on the method page.
- Time to first formal review: PR creation to the first submitted review by a non-author, non-bot.
- Time to first human response: PR creation to the first non-author, non-bot comment or review.
  Both are stored; the report leads with formal review and notes repos that approve through comments.
- Merge rate = merged / (merged + closed unmerged), counting only PRs created at least 30 days before the
  data snapshot. Open PRs are shown separately and never counted in the rate.
- Minimum sample: 10 mature newcomer PRs per area; below that, "not enough data".
- Distinct newcomer authors: the number of different non-bot newcomer authors behind an area's mature
  newcomer PRs. Shown next to the sample size, because 12 PRs from 3 people is not 12 PRs from 12.
- Author concentration flag: raised when a single author accounts for more than 30% of an area's mature
  newcomer PRs. Configurable. The report says the sample is dominated by one contributor.
- Stale open: newcomer PRs still open more than 90 days after creation. Configurable. These stay out of
  the merge rate, which only counts merged and closed-unmerged PRs, so an area that neither merges nor
  closes newcomer work would otherwise look the same as one with no backlog. Shown per area, and the
  method page explains that a high stale-open count alongside a good merge rate means newcomer PRs are
  often simply left waiting.
- Repo rate: the mature newcomer merge rate across the whole repo, used as the comparison point for banding.
- Banding: the 95% Wilson score interval of an area's mature newcomer merge rate, compared with the repo rate
  as described in report section 1.
- Nobody is called a maintainer or an owner anywhere in v0, because v0 ships no ownership data.
  Never show per-person review speed.

## Architecture
Fixed:
- ingest:
  - Clone with --filter=blob:none --no-checkout into /data/repos/ for commit history and changed file paths.
    No file contents and no API cost.
  - Resolve the repo's canonical nameWithOwner before any search query, and store both the requested and
    the canonical slug.
  - GitHub GraphQL API for PRs (author, authorAssociation, created/merged/closed times, all changed file
    paths with pagination, first reviews and comments).
  - Pagination, rate-limit tracking via the API's rateLimit field, retry with exponential backoff on the
    whole transport exception group, and checkpoints so an interrupted run resumes instead of restarting.
- metrics: pure functions that turn stored rows into area stats, newcomer stats and bands.
- jobs: a jobs table and one worker process claiming jobs with SELECT ... FOR UPDATE SKIP LOCKED,
  GET /jobs/{id} progress, and progressive results (areas map first). Confirmed by Phase 0 timings.
- API (FastAPI, one service):
  - POST /analyze {repo_url}: validates a public github.com/owner/repo URL, returns the cached report
    or starts an analysis.
  - GET /repos: analyzed repos.
  - GET /repos/{owner}/{repo}/report: the full report.
  - GET /jobs/{id}: progress.
- web (Next.js): / paste a URL + list of analyzed repos; /r/{owner}/{repo} report (Where to start first);
  /method definitions and validation.
Decided in Phase 1:
- No incremental refresh CLI in v0; a repo is re-analyzed in full. See docs/decisions/0007.

## Tables
repos, prs, pr_areas, area_stats, jobs. Nothing else.
Store only what the metrics need; never store file contents.

## Evaluation (results in results/; each with a written method)
- Newcomer-friendliness validation: pick a cutoff date (for example 6 months before the snapshot).
  Band areas using ONLY data before the cutoff; then measure each area's actual mature newcomer merge rate
  after it. Report whether areas banded "above repo average" before the cutoff stayed above the repo rate
  after it, with counts and a bootstrap 95% CI on that proportion. Include only areas meeting the minimum
  sample in both periods; report sample sizes. Run on at least 3 repos. Report weak or negative results
  honestly.
- Performance: time to first result and full analysis, plus API points used, for a small, medium and huge repo.

## Stack and limits
Python 3.14, FastAPI, psycopg 3, httpx, Postgres, git CLI, scipy. pytest, ruff. Next.js for the web pages.
No Celery, Redis, Kafka, LangChain, ORM, microservices, LLM or embeddings in v0.
Public repos only, one shared read-only token, free tiers only. No API hosting in v0; "paste any URL" is
local-only.

## Reference repositories
Keep these three as the reference set for all measurements and evaluations:
Kludex/starlette (small, reached as encode/starlette), optuna/optuna (medium), kubernetes/kubernetes (huge).

## Milestones
M1 skeleton + config + schema + Postgres + GitHub Actions CI workflow file (ruff + pytest on Python 3.14, on push)
M2 clone ingest + commit-based area activity + contributors
M3 GraphQL PR ingest (monthly sampling, files pagination, rate-limit tracking, checkpoints) + first-timer
   lookback + response, merge-rate and Wilson banding metrics + sample notes
M4 API + queue and worker (STOP: I try it on 3 repos)
M5 web pages (home, report with Where to start first, method)
M6 validation + performance numbers + README with quickstart and screenshots
Stretch (each only after I approve):
- potentially available starter issues: open issues with newcomer labels (good first issue, help wanted;
  configurable), each showing assignee, linked open PR, and claim comment in the last 30 days (including
  slash commands such as /assign). Classified as "potentially available" or "likely taken", never
  "definitely unclaimed". Includes the availability check: manually label 30-50 starter issues across a
  wider repo set than the reference three, and report precision and recall of "potentially available".
- ownership: parse CODEOWNERS (standard paths only, never globbed) and Kubernetes-style per-directory
  OWNERS files, labelling which file each claim came from.
- export reports of pre-analyzed repos as static pages for Vercel.
- nightly refresh; compare 2-3 repos side by side; hidden file coupling; "how PRs get merged here" norms.

## Defense pack (after the last approved milestone)
docs/defense.md: one-page plain-English walkthrough; one short paragraph per component (what, why, how,
what breaks); every trade-off as "chose X over Y because Z; would revisit if W"; 15 likely interview
questions with short answers (GraphQL vs REST, rate limits and checkpoints, blobless no-checkout clones,
files pagination, queue vs synchronous decision, merge-rate denominator and maturity, Wilson intervals and
why bands instead of a ranking, formal review vs human response, bot filtering, first-timer lookback,
monthly sampling and what "sampled" means, canonical repo names and renames, cutoff validation, caching,
privacy of contributor data); an honest limitations section.
Put 3 resume bullets using only numbers from results/ in notes/resume.md, not in the repo docs.
