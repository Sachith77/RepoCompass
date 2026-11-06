# RepoCompass: how it works and why

A plain-English guide to the design, its trade-offs and its limits. Sources for the numbers:

- `results/` for the v0 runs; `results/performance.md` collects the timings.
- `docs/00-feasibility.md` and `results/phase0/` for Phase 0.
- `docs/decisions/` (the ADRs) for the decisions.
- `results/validation/` for the validation.

Numbers are measured unless marked *calculated*.

## The walkthrough

RepoCompass answers one question: *if I want to contribute to this repository, where might I start?*

**The job.** You paste a GitHub repository. The API does not analyse it on the spot: it writes a job
into a Postgres table and answers at once. A separate worker process picks the job up and does the
slow work in four stages.

1. **Clone.** It looks up the repository's current name, then makes a *blobless, no-checkout* clone.
   That holds the full commit history and the file names, but not the file contents. A cold kubernetes
   clone of this kind took 71.7 s.
2. **Areas and activity.** It splits the file tree into **areas**: directories, at a depth fitted to
   each repository. Then it reads 12 months of commits to see which areas are active. Apart from the
   one name lookup this stage uses only the clone, so it is ready quickly. With the clone already on
   disk it took 2 to 6 s, and the page shows it early.
3. **Pull requests.** It pages through the last 12 months of pull requests using GitHub's GraphQL API.
   It drops bots and keeps at most 250 human PRs per calendar month. Each PR is reduced to per-area
   file counts, response times and reviewer logins.
4. **Newcomers and metrics.** For every author it asks GitHub for their earliest merged PR. A PR is a
   **newcomer PR** if its author had no merged PR in the repository created before it. Then, per area,
   it computes three things:
   - the **merge rate** of finished newcomer PRs;
   - a 95% **Wilson interval** around that rate;
   - a **band**: above, below, or no clear difference from the repository's own rate.

**Saving.** All of a repository's rows are replaced in one database transaction, so a reader never
sees half of a new analysis next to half of an old one. During the run, progress is saved as a
checkpoint in the job row, so an interrupted job can continue where it stopped.

**The report.** It opens with a few plain sentences built by fixed rules. Then come a chart of every
area's interval against the repo average, one card per area, and a table of where work happens.
Areas are never ranked 1-2-3, because at real sample sizes their intervals overlap (ADR-0003).

**Measured end to end**, with clones already on disk:

| Repository | Analysis time | API points used (of 5,000 an hour) |
|---|---|---|
| Kludex/starlette | 120 s | 49 |
| optuna/optuna | 96 s | 31 |
| kubernetes/kubernetes | 2,080 s | 606 |

## The components

**GitHub client** (`github.py`). This is the only code that calls the GitHub API, and it uses GraphQL
only. One request returns a page of 50 PRs with their files, reviews and comments for 1 to 2 points.
It retries transport errors and HTTP 502, 503 and 504 with exponential backoff, and it waits out
secondary rate limits. It reads `rateLimit` on every response and stops cleanly when fewer than 100
points are left. A revoked token, a private repository or a long GitHub outage makes the job fail,
with its checkpoint kept.

**Clone and areas** (`gitclone.py`, `areas.py`, `activity.py`). Git history costs no API points, so
area activity comes from a local clone. The area rule groups files by top-level directory, and splits
any group holding more than a quarter of the files one level deeper, up to four levels (ADR-0006).
`git log` runs with `--no-renames`, because rename detection would make a blobless clone download file
contents. On pallets/click that meant 25 objects; with `--no-renames`, 12 months of kubernetes history
read in 0.6 s with nothing downloaded. Commits that touch more than half of all areas, and at least
five, are treated as sweeps and ignored. Two things break it:
- a repository whose real units are not directories, such as a monorepo keyed on package files;
- one person with two emails, who counts twice, because no mailmap is read.

**PR ingest** (`prs.py`). This reads the 12-month PR window, because PRs carry the outcome being
measured. Bot PRs are dropped first, then at most 250 human PRs are kept per month, newest first
(ADR-0004).

A PR with more than 100 changed files gets follow-up requests until its file list is complete. In
Phase 0, over the newest 3,000 kubernetes PRs, that was 83 PRs and 322 extra requests. A list that
cannot be completed is marked and left out, never truncated.

What breaks is time: kubernetes had to page through all 6,619 human PRs in its window to count every
month, and kept 3,082.

**First-timer lookback** (`lookback.py`). This decides which PRs are newcomer PRs. GitHub's
`authorAssociation` field describes the author as they are today: in a Phase 0 sample of 60 PRs it
disagreed with the real history on 9 (ADR-0002). Instead, one search per author finds their earliest
merged PR, batched 20 searches per request with GraphQL aliases. On optuna that was 8 requests, where
one request per author would have been 148 (*calculated*: 148 authors). Contributions made by direct push, or
before a move to GitHub, are invisible, so those authors count as newcomers.

**Metrics and report** (`metrics.py`, `report.py`). Pure functions turn PR records into rates,
intervals, bands, medians and counts, so each rule can be pinned by a unit test. The merge rate is
merged / (merged + closed unmerged), over **mature** newcomer PRs only: PRs created at least 30 days
before the snapshot and no longer open. Nothing here fails at run time. The risk is misreading: a band
describes the past, not how easy an area is.

**Storage** (`db.py`, `schema.sql`). Five Postgres tables (`repos`, `prs`, `pr_areas`, `area_stats`
and `jobs`) are queried with plain SQL through psycopg, with no ORM. One transaction replaces all of a
repository's rows (ADR-0008). Every row can be rebuilt from public data. So when the schema changes,
the tables are dropped and the repositories analysed again.

**Jobs and worker** (`jobs.py`, `worker.py`, `analysis.py`). Analyses take minutes, and in Phase 0 a
long run that saved only at the end lost two finished repositories when GitHub dropped the connection
(ADR-0005). So the worker claims the oldest queued job with `FOR UPDATE SKIP LOCKED`, and checkpoints
after the git stage, every PR page and every lookback request. An interrupted or failed job can be continued in
three ways:
- a new `POST /analyze` for the same name re-queues it, if its data is under 24 hours old and the
  repository has no stored report yet;
- `python -m repocompass resume JOB_ID` continues it at any age;
- stopping the worker with Ctrl+C puts a running job back in the queue.

The measured case was unplanned: a kubernetes job stopped at 30% of its PR pages when the machine ran
low on memory. The resumed job ended with the same totals as an uninterrupted run (473 requests, 606
points), and the worker's memory peaked at 72 MB. The limit is that one worker runs jobs one at a
time, so a kubernetes analysis delays everything behind it.

**API** (`api.py`). FastAPI on 127.0.0.1 serves `POST /analyze`, `GET /jobs/{id}`, `GET /repos` and
the report. It never calls GitHub, so a request never waits minutes or fails halfway. It returns the
stored report if there is one; otherwise it queues a job, and never two for the same name. CORS admits
only the local web origins. If Postgres is down it returns 503.

**Web pages** (`web/`, Next.js). The home, report and method pages fetch from the API in the browser
and poll a running job every 2 s. The report has to be readable by someone who has never heard of a
Wilson interval. The chart is an SVG drawn at its container's measured width; each row takes keyboard
focus, and a hidden table carries the same numbers. The pages only show what the API returns, so
without the API they show its error.

**Validation** (`validation.py`, `validation_report.py`, `validate_cmd.py`). A band is only useful if
it says something about the future. So bands are rebuilt from PRs created before a cutoff and compared
with what happened after it. The result so far is too small to conclude anything; see Limitations.

## Trade-offs

- **Clone and GraphQL.**
  - *Chose:* a blobless clone plus GraphQL, over a full clone or REST for everything.
  - *Because:* the clone gives history at no API cost, and GraphQL returns files, reviews and comments
    with each page of PRs.
  - *Would revisit if:* file contents entered scope.
- **Own newcomer rule.**
  - *Chose:* our own rule, over `authorAssociation`.
  - *Because:* that field is evaluated at query time. It pushes successful first PRs out of the
    newcomer pool, which would bias the merge rate down.
  - *Would revisit if:* GitHub exposed a point-in-time association.
- **Bands.**
  - *Chose:* bands, over ordering areas by their Wilson lower bound.
  - *Because:* on optuna in Phase 0, three areas had intervals about 0.4 wide that overlapped almost
    entirely.
  - *Would revisit if:* areas had several times more newcomer PRs.
- **Monthly cap.**
  - *Chose:* a cap per month, over a flat cap on the newest 3,000 PRs.
  - *Because:* on kubernetes in Phase 0, the flat cap kept only the newest 134 days, 37% of the
    "12-month" window.
  - *Would revisit if:* months grew so large that 250 stopped being representative.
- **Queue and worker.**
  - *Chose:* a jobs table and a worker, over analysing inside the HTTP request.
  - *Because:* the brief's limit for a synchronous request was about 60 s. Of the three Phase 0 cold
    times, two passed it (81 s small, 986 s huge) and the medium one was close (56 s). Resuming also
    needed somewhere to keep a checkpoint.
  - *Would revisit if:* an analysis took a few seconds.
- **Full re-analysis.**
  - *Chose:* full re-analysis, over an incremental refresh.
  - *Because:* the window, the maturity rule and the newcomer flags all shift together, so an
    incremental update would recompute most rows anyway.
  - *Would revisit if:* many repositories were refreshed nightly.
- **One transaction.**
  - *Chose:* one transaction, over writing each stage as it finishes.
  - *Because:* bands depend on the repo rate, which depends on every newcomer flag.
  - *Would revisit if:* the transaction grew too large. The monthly cap bounds it at 3,250 PR rows
    (*calculated*: 13 months × 250, for the 365-day window).
- **Plain SQL.**
  - *Chose:* plain SQL, over an ORM.
  - *Because:* five tables and a handful of queries are easier to read and explain as SQL.
  - *Would revisit if:* the schema grew past what a reader can hold in their head.

## Likely interview questions

1. **Why GraphQL rather than REST?** One GraphQL page returns 50 PRs with their files, reviews and
   comments for 1 to 2 points. REST would need separate calls per PR for files and for reviews.

2. **How do you handle rate limits and failures?** Every response reports the points left, and the
   client stops cleanly with 100 in reserve. Transport errors and 502, 503 and 504 are retried with
   backoff. Progress is checkpointed after every page, so a failed job resumes. Measured on kubernetes,
   the resumed job ended with the same totals as an uninterrupted run.

3. **What is a blobless, no-checkout clone?** `git clone --filter=blob:none --no-checkout` downloads
   commits and trees but no file contents, and writes no working copy. That is all the area rule and
   the activity counts need. `--no-renames` stops git from downloading contents to detect renames.

4. **How do you get every changed file of a big PR?** The first 100 files come inline. A PR with more
   gets follow-up requests until its list is complete. If the list cannot be completed, including past
   GitHub's 3,000-file listing, the PR is left out of area figures rather than truncated.

5. **Why a queue instead of answering the request directly?** Two of the three Phase 0 cold analyses
   took longer than the brief's synchronous limit of about 60 s, and the third took 56 s. A job row
   also gives the checkpoint somewhere to live. `SKIP LOCKED` in Postgres avoids adding Redis or Celery.

6. **What is the merge-rate denominator, and why "mature"?** The rate is merged / (merged + closed
   without merging). Open PRs are left out. So are PRs younger than 30 days, which have not had time to
   be decided. Newcomer PRs still open after 90 days are shown separately as "stale open".

7. **Why Wilson intervals, and why bands instead of a ranking?**
   - Banded areas are small: optuna's had 12 to 28 finished newcomer PRs each. At that size a raw
     percentage is noisy.
   - The Wilson interval behaves well for small samples and for rates near 0 or 1.
   - The intervals overlap so much that a 1-2-3 order would claim a precision the data does not have.
     So an area is only marked above, below or no clear difference.

8. **Formal review or human response?**
   - A *formal review* is a submitted review by someone other than the author.
   - A *human response* is the earlier of that and a comment by a person.
   - Formal-review coverage ranged from 16.8% to 73.5% across the Phase 0 reference repositories, and
     from 19.5% to 78.2% in the current v0 reports.
   - So the report leads with formal review only when at least half of PRs get one. Otherwise it uses
     any human reply. Both medians are stored, each with its count.

9. **How are bots filtered?** A login is treated as a bot if any of these holds:
   - GitHub types the account as a Bot;
   - the login ends in `[bot]`;
   - it is on a configurable list, for example dependabot and k8s-ci-robot.

   Bots are removed as authors, reviewers and commenters, and their PRs are dropped before the monthly
   cap.

10. **How do you decide someone is a first-time contributor?** One search per author returns their
    earliest merged PR in the repository, over all its history. A PR is a newcomer PR when nothing by
    that author merged earlier. Searches are batched 20 per request.

11. **What does "sampled" mean?** At most 250 human PRs are kept per calendar month, the newest in that
    month. If any month hit the cap, the report says "Sampled" and shows the per-month counts and the
    dates covered. It is not a random sample, and the method page says so.

12. **What happens when a repository was renamed or moved?** The worker looks up the current name
    before anything else and stores both names. Search is keyed on the current name, so
    `encode/starlette` would otherwise have returned zero PRs. The report shows "previously
    encode/starlette".

13. **How did you validate the bands?** With cutoff validation: bands are built from PRs before a
    cutoff, then checked against merge rates after it. Every directional band that could be tested
    held, but that was only 4 areas across two runs. It is a null result: the bands are neither shown to
    predict nor shown to fail.

14. **Is anything cached?** A finished report is stored and returned as is. The API answers "cached"
    and never re-analyses by itself. The clone stays on disk, so the next analysis only fetches. A fresh
    report comes from `python -m repocompass analyze`, which rebuilds everything.

15. **What about contributor privacy?** Only public GitHub data is read. Stored in the database:
    - for every sampled PR: the author's login, its created, merged and closed times, and its
      `author_association`;
    - per area: logins with counts of merged PRs and reviews.

    The job checkpoint also holds reviewer logins per PR and the creation date of each author's
    earliest merged PR.
    Commit emails are used to count authors and are never written to the database, but the clones in
    `data/repos/` contain the full history, emails included, as any clone does. No PR titles or text
    are kept. Nobody is called a maintainer or an owner, and no per-person speed is shown.

## Limitations

- **The validation is a null result.**
  - *12-month run:* starlette, optuna and sqlfluff, with the cutoff 182 days back. 4 areas qualified in
    both periods, and both "below" bands held. No "above" band qualified.
  - *24-month run:* optuna, sqlfluff, pydantic and fastapi, with the cutoff 365 days back. 11 areas
    qualified. One "above" band (pydantic `docs`) and one "below" band (the `pydantic` package) held.
  - *Why it proves nothing:* four directional areas are too few to say whether bands predict anything.
    Most of the extra areas came from the added repositories, and the longer window's own effect was not
    separated.
  - *Other caveats:*
    - the repo rate fell between the periods in every 24-month repository (fastapi from 0.275 to 0.054),
      and the cause was not checked;
    - newcomer flags could carry information from after the cutoff, by at most 3 to 32 PRs per
      repository (upper bounds).
- **A band describes the past, not difficulty.** PR size, contributor experience, maintainer time and
  release cycles all move merge rates.
- **Most areas show "no clear difference",** because samples per area are small.
- **Newcomers are judged from PRs only.** Direct pushes and history from before GitHub are invisible.
- **Response times can be unknown.** Only the first 20 reviews and 30 comments of a PR are read. A
  PR's response times are marked unknown when either list was cut short with no human answer in it.
- **Busy repositories are sampled,** newest first within each month, so a capped month is not a random
  sample.
- **Areas are fitted to the current file tree.** A PR whose files are no longer in any current area
  counts toward no area, though it still counts in the repo rate.
- **It runs locally only,** with no hosted version and a single worker.
- **The web pages have no automated tests.** Their checks are type checking, linting and a production
  build. The Python side has unit tests and, with a database, integration tests.
