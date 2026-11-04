# RepoCompass

**If I want to contribute to this repository, where might I start?**

Paste a public GitHub repository and RepoCompass reads its git history and its pull requests, then
shows how newcomers have fared in each part of it: how often their PRs were merged, how quickly they
got an answer, and which areas are active. Every area merge rate comes with its sample size and a 95%
interval, and nothing is ranked: areas are only marked as above, below, or not clearly different from
the repository's own newcomer merge rate.

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

Needs Python 3.14, PostgreSQL, git, Node.js 24, and a GitHub token (read-only access to public
repositories is enough).

Run every command from the project folder (clone and result paths are relative to it).

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned   # lets this shell run Activate.ps1
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env        # then fill in GITHUB_TOKEN and DATABASE_URL
python -m repocompass init-db
```

Then three processes, each in its own terminal:

```powershell
python -m repocompass worker   # runs queued analyses
python -m repocompass serve    # the API on http://127.0.0.1:8000
cd web; npm ci; npm run dev    # the pages on http://localhost:3000
```

Open http://localhost:3000 and paste a repository URL. A small repository takes about two minutes; the
page shows the areas map within seconds and updates itself until the report is ready. Without the web
pages, `python -m repocompass analyze owner/repo` runs one analysis at the command line.

## Measured results

Measured on one laptop with a local database; details in `results/performance.md`.

| repository | full analysis | areas map shown after | API points |
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
- Only the first 20 reviews and 30 comments of a PR are read; response times are marked unknown when no
  human answer is among them.
- Busy months are capped at 250 human PRs, keeping the newest, so large repositories are sampled.
- It runs locally only; there is no hosted version.

## Development

```powershell
pytest                   # integration tests run only when TEST_DATABASE_URL is set
ruff check .; ruff format --check .
cd web; npm run lint; npm run build; npm run typecheck
```

Design notes are in `docs/DESIGN.md` and the decisions in `docs/decisions/`.

## Licence

MIT. See `LICENSE`.
