# RepoCompass

**If I want to contribute to this repository, where might I start?**

Paste a public GitHub repository and RepoCompass reads its git history and its pull requests, then
shows how newcomers have fared in each part of it: how often their PRs were merged, how quickly they
got an answer, and which areas are active. Every area merge rate comes with its sample size and a 95%
interval, and nothing is ranked: areas are only marked as above, below, or not clearly different from
the repository's own newcomer merge rate.

![The top of a report for Kludex/starlette: a summary paragraph, then each area's merge rate with its 95% interval against the repo average](docs/images/report-lead-and-chart.png)

*The top of a report (Kludex/starlette, snapshot 2026-11-03): the summary, then each area's newcomer
merge rate as a mark on its 95% interval, against the repo average line.*

![One area card for the docs area: 45% merged, 20 of 44, 40 authors, with reviewers and example PRs](docs/images/area-card.png)

*One area card: the merge rate and its sample, response time with the share that got no reply,
reviewers to tag and merged newcomer PRs to read.*

![The home page: the question, a box for a repository URL, how to read a report, and example repositories](docs/images/home.png)

*The home page.*

## What the report shows

1. **Summary**: two or three plain sentences built by fixed rules from the numbers below.
2. **Where to start**: each area with enough data (at least 10 newcomer PRs that were merged or
   closed and are at least 30 days old), banded by its
   95% Wilson interval against the repo rate, with a chart of the intervals, the number of distinct
   authors behind each sample, stale open PRs, response times paired with the share that got no response,
   and example merged newcomer PRs to read. Areas with too little data are listed separately.
3. **Areas map**: commit activity per area over 90 days and 12 months, and the people whose PRs were
   merged and who reviewed there (counts only; nobody is called a maintainer or owner).
4. **Data and sample**: the window, how many PRs were kept, dropped or sampled per month, and the
   parameters the analysis used. A report whose months were capped says "Sampled" and gives the dates
   it covers.

The method page (`/method`) defines every metric in plain English.

## Quickstart

Needs Python 3.14, PostgreSQL (with an empty database for RepoCompass), git, Node.js 24, and a
GitHub token (a fine-grained token with read-only access to public repositories is enough). The
commands below are for Windows PowerShell.

> - Start the worker, or analyses will stay queued.
> - Analysing kubernetes takes about 35 minutes (measured: 2,080 s, `results/performance.md`).
> - On Windows, `createdb` may need its full path, for example
>   `C:\Program Files\PostgreSQL\18\bin\createdb.exe`.

Run every command from the project folder (clone and result paths are relative to it).

```powershell
createdb -U postgres repocompass   # or create an empty database any other way (e.g. pgAdmin)
py -3.14 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned   # lets this shell run Activate.ps1
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env        # then fill in GITHUB_TOKEN and DATABASE_URL
python -m repocompass check   # shows the configuration it found, without printing secrets
python -m repocompass init-db # creates the five tables
```

`DATABASE_URL` looks like `postgresql://user:password@localhost:5432/repocompass`.

Then three processes, each in its own terminal opened in the project folder. In the first two,
run the `Set-ExecutionPolicy` and `Activate.ps1` lines again first.

```powershell
python -m repocompass worker   # runs queued analyses
python -m repocompass serve    # the API on http://127.0.0.1:8000
cd web; npm ci; npm run dev    # the pages on http://localhost:3000
```

Open http://localhost:3000 and paste a repository URL. In the measured runs below (clones already on
disk), a small repository took about two minutes and the areas map appeared after 2 to 6 s; the page
updates itself until the report is ready. Clones go to `data/repos/`. `npm run dev` downloads the
page fonts from Google Fonts when it starts; if it starts offline, the pages use system fonts until it
is restarted. Without the web pages, `python -m repocompass analyze owner/repo` runs one analysis at
the command line.

Once a repository has a report, pasting it again shows that stored report. To refresh it, run
`python -m repocompass analyze owner/repo`, which rebuilds it from scratch.

## Measured results

Measured on one laptop with a local database; details in `results/performance.md`.

| repository | full analysis | areas map shown after | API points (GraphQL rate limit, 5,000 an hour) |
|---|---|---|---|
| Kludex/starlette (small) | 120 s | 2 s | 49 |
| optuna/optuna (medium) | 96 s | 2 s | 31 |
| sqlfluff/sqlfluff (medium) | 219 s (command line, not the worker) | not measured | 75 |
| kubernetes/kubernetes (huge) | 2,080 s | 6 s | 606 |

An interrupted kubernetes analysis resumed from its checkpoint with the same total API cost as an
uninterrupted run (so, reasoned from that, no page was fetched twice), with a
peak worker memory of 72 MB (`results/m4/resume_test.md`).

**Validation** (`results/validation/`): bands were made from data before a cutoff and checked against
what happened after it, in two runs: 12-month analyses with a cutoff six months back (starlette, optuna,
sqlfluff) and 24-month analyses with a cutoff a year back (optuna, sqlfluff, pydantic, fastapi). Every
directional band that could be tested held: 2 of 2 "below" areas in the first run, 1 "above" and 1
"below" area in the second. Four areas are far too few for a conclusion: this is a null result.

## Limitations

- A band describes what happened, not how easy an area is. Contributor experience, PR size, maintainer
  availability, release cycles and contribution guidelines all affect merge rates.
- Samples per area are small, so most areas show "no clear difference", and the validation above could
  not confirm that the bands predict anything.
- A newcomer PR is one whose author had no merged PR in the repository created before it, judged from pull
  requests only; contributions by direct push are invisible.
- Only the first 20 reviews and 30 comments of a PR are read; its response times are marked unknown when
  either list was cut short with no human answer in it.
- Busy months are capped at 250 human PRs, keeping the newest, so large repositories are sampled.
- It runs locally only; there is no hosted version.

## Development

```powershell
pytest                   # integration tests run only when TEST_DATABASE_URL is set; point it at a separate, empty database
ruff check .; ruff format --check .
cd web; npm run lint; npm run build; npm run typecheck
```

Design notes are in `docs/DESIGN.md`, the decisions in `docs/decisions/`, a plain-English walkthrough
in `docs/defense.md`, and the Phase 0 measurements in `docs/00-feasibility.md`.

## Licence

MIT. See `LICENSE`.
