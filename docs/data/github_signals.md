# GitHub signals: what the data actually looks like

Snapshot date: 2026-11-03. All figures below were produced by measurement scripts run against the
live GitHub API and local clones on that date. Every figure is labelled **measured** or **estimated**.
Raw output lives in `results/phase0/`.

Repositories studied:

| role | requested | canonical | PRs created in last 12 months (measured) |
|---|---|---|---|
| small | `encode/starlette` | `Kludex/starlette` | 560 |
| medium | `optuna/optuna` | `optuna/optuna` | 526 |
| huge | `kubernetes/kubernetes` | `kubernetes/kubernetes` | 6,616 |
| dormant control | `encode/httpx` | `encode/httpx` | 54 |

`encode/httpx` was kept as a deliberate control: it has 3 commits in 12 months and 0 in the last
3 months (measured), so it shows what the report must do when a repo has almost no recent activity.

---

## 1. Repository identity must be resolved before anything else

**Finding (measured).** `encode/starlette` is now `Kludex/starlette`. The two API surfaces disagree
about renamed repositories:

| lookup | result for `encode/starlette` |
|---|---|
| `repository(owner: "encode", name: "starlette")` | follows the rename, returns the live repo |
| `search(query: "repo:encode/starlette is:pr …")` | returns `issueCount: 0` |

The search index is keyed on a repository's *current* name. A rename therefore produces a report
that looks successful and says the repo has zero pull requests.

**Decision.** Resolve `nameWithOwner` with a `repository(owner, name)` lookup first, store it, and
build every later `search()` query from the canonical value. Record both the requested and the
canonical slug so a redirect is visible on the report.

Source: `results/phase0/identity_check.json`.

---

## 2. Bots

Bot share of sampled PRs (measured): `Kludex/starlette` 4.7%, `optuna/optuna` 2.0%,
`kubernetes/kubernetes` 0.0% of PR authors in the mature sample.

Kubernetes is the instructive case: its bot traffic is almost entirely *comments* from
`k8s-ci-robot`, not authored PRs. A bot filter that only checks PR authorship will leave bot
comments in the response-time metric.

**Decision.** Exclude an actor when any of these hold: GraphQL `__typename == "Bot"`, login ends in
`[bot]`, or login appears in a configurable list. Apply the filter to PR authors, review authors and
comment authors alike. Seed the list with `dependabot`, `renovate`, `github-actions`, `k8s-ci-robot`,
`codecov`.

---

## 3. First-time contributor: use our own rule, not `authorAssociation`

20 mature PRs per repo were classified both ways (measured).

| repo | agreement | `authorAssociation` says newcomer, our rule disagrees | our rule says newcomer, `authorAssociation` disagrees |
|---|---|---|---|
| `Kludex/starlette` | 18/20 (90%) | 0 | 2 |
| `optuna/optuna` | 15/20 (75%) | 0 | 5 |
| `kubernetes/kubernetes` | 18/20 (90%) | 1 | 1 |
| **total** | **51/60 (85%)** | **1** | **8** |

**Why they disagree.** Two distinct problems, both visible in the data:

1. `authorAssociation` is evaluated **when you query**, not when the PR was opened. Eight of the nine
   disagreements are authors now reported as `CONTRIBUTOR` whose PR *was* their first; every one has
   a small all-time merged count (1–5 merged PRs, measured). Their status changed because that very
   PR merged.
2. `NONE` does not mean "first-timer". It means "no association with the repository". Kubernetes
   PR 142663 is authored by someone still reported as `NONE` who already had an earlier merged PR.

Problem 1 matters most, because the bias is **correlated with the outcome being measured**. An author
whose first PR merged stops being labelled a newcomer, while an author whose first PR was rejected
stays `NONE`. Using `authorAssociation` would therefore drop successful first PRs out of the newcomer
pool and bias the newcomer merge rate downward.

**Decision.** Define a newcomer PR as: *no merged pull request by this author in this repository was
created before this one*, checked across the repository's entire history.

**Cost (measured).** One `search` query per **distinct author** returns their earliest merged PR, so
the lookback scales with authors, not PRs. Batching 20 author searches into one request with GraphQL
aliases reduced `optuna/optuna` from 148 requests to 8, taking 24.5 s for 148 authors.

**Limitation to state on the method page.** The lookback uses the repository's PR history only. A PR
merged before the repository was migrated to GitHub, or commits landed outside the PR flow, are
invisible to it. Someone who contributed only by direct push will still be counted as a newcomer.

Sources: `results/phase0/firsttimer_and_reviews.json`, `results/phase0/end_to_end_medium.json`.

---

## 4. Formal review and human response are different metrics

Measured on PRs created inside the 12-month window **and at least 30 days before the snapshot**, so
every sampled PR had time to be answered. Sample sizes: 143, 147 and 150 non-bot PRs.

| repo | has formal review | comment only, no formal review | no human response | median hours to first formal review | median hours to first human response |
|---|---|---|---|---|---|
| `Kludex/starlette` | 16.8% | 11 | 108 | 55.2 | 71.7 |
| `optuna/optuna` | 73.5% | 25 | 14 | 59.0 | 27.0 |
| `kubernetes/kubernetes` | 42.0% | 49 | 38 | 56.6 | 17.6 |

Three things follow from this table.

**Formal review coverage varies enormously** — 16.8% to 73.5%. Leading the report with "median time
to first formal review" would leave `Kludex/starlette` reporting a number drawn from 24 of 143 PRs.

**Kubernetes approves through comments.** 49 of 150 PRs got a human comment but no submitted review,
and its median first human response (17.6 h) is less than a third of its median first formal review
(56.6 h). This is the `/lgtm` convention: approval arrives as a comment.

**The two medians are computed over different PR sets**, which is why `Kludex/starlette` shows a
*slower* median human response (71.7 h) than formal review (55.2 h). The 11 comment-only PRs there
were answered slowly, and they enter the response median but not the review median. Per PR, first
human response is always at or before first formal review; across different subsets it need not be.

**Decision.** Store both timestamps on every PR. Lead the report with time to first formal review,
and when a repo's formal-review coverage is below a configurable share (50% is the suggested
starting point), show first human response as the headline instead and say why. Always print the
sample size each median was computed from.

**Measurement caveat.** Reviews were read at `first: 20` and comments at `first: 30`. The count of
PRs where a human might have been hidden beyond that slice was **0** in all three repos (measured),
so these slice sizes are adequate for these repos, but the ingest should still page rather than
assume.

---

## 5. Starter issues: the open backlog is usually empty

Measured open-issue counts:

| repo | open issues (all) | open `good first issue` | open `help wanted` | open and unassigned | closed with those labels |
|---|---|---|---|---|---|
| `Kludex/starlette` | 4 | 0 | 0 | 0 | 39 |
| `optuna/optuna` | 15 | 0 | 0 | 0 | 411 |
| `kubernetes/kubernetes` | 1,901 | 6 | 141 | 23 | 946 |

`optuna/optuna` has closed 299 `contribution-welcome` issues and 103 `good first issue` issues, and
currently has **none open**. The labels are used heavily; the backlog is simply triaged to zero.
Only `kubernetes/kubernetes` has a usable supply, and its 6 open `good first issue` entries are
**all assigned**.

Availability signals on 20 sampled kubernetes issues (measured):

| signal | count |
|---|---|
| has an assignee | 20 / 20 |
| has a linked open PR | 0 / 20 |
| has a claim comment in the last 30 days | 13 / 20 |

Claim phrases actually observed, in frequency order: `/assign` (12), "can I work on / pick up / have"
(5), "I'd like to work on" (1), "can I take" (1), "I'll take / work on" (1). The dominant pattern is
a **bot command, not prose** — kubernetes uses prow's `/assign`. Any phrase list that only matches
English sentences will miss most real claims on prow-based repositories.

**Decisions.**
- Keep the three signals as specified, and keep the "potentially available" / "likely taken" wording.
- Put `/assign` and similar slash commands at the top of the claim phrase list.
- Treat this section as **secondary** on the report, and render an explicit empty state: "this
  repository has no open issues carrying newcomer labels" is the common case, not an error.
- The availability evaluation in the brief wants 30–50 manually labelled issues. Across these three
  repositories only 147 open labelled issues exist and 141 of them are kubernetes `help wanted`.
  That evaluation needs a wider repository set to avoid being a single-repo measurement.

Sources: `results/phase0/starter_issues.json`, `results/phase0/issue_label_verify.json`.

---

## 6. Areas: a fixed one-or-two-level rule does not fit

File counts are from `git ls-tree -r HEAD` on the local clones (measured, no API cost). Vendored and
generated directories (`vendor`, `third_party`, `node_modules`, `LICENSES`, `CHANGELOG`) are excluded
before any rule is applied.

| repo | one level | largest area share | two levels | largest area share |
|---|---|---|---|---|
| `Kludex/starlette` | 7 areas | 24.5% | 7 areas | 24.5% |
| `optuna/optuna` | 6 areas | 46.5% | 20 areas | 26.4% |
| `kubernetes/kubernetes` | 13 areas | 64.9% | 16 areas | **64.8%** |

Two levels fixes `optuna/optuna` and does essentially nothing for `kubernetes/kubernetes`, because
`staging/` contains `staging/src/k8s.io/<package>/`. Splitting one level deeper just renames the
giant area from `staging` (16,942 files) to `staging/src` (16,935 files).

**Rule adopted, in plain words:** group files by their top directory; if one group holds more than a
quarter of the files, split that group one level deeper; repeat until no group is oversized, up to
four levels. The depth is fitted per repository from its own file tree and printed on the report.

Result (measured):

| repo | depth chosen | areas | largest area | its share |
|---|---|---|---|---|
| `Kludex/starlette` | all roots 1 | 7 | `starlette` | 24.5% |
| `optuna/optuna` | `optuna` 2, `tests` 2 | 32 | `docs` | 15.5% |
| `kubernetes/kubernetes` | `staging` 4 | 50 | `staging/src/k8s.io/pod-security-admission` | 18.5% |

For kubernetes this produces areas a newcomer would recognise: `staging/src/k8s.io/api`,
`staging/src/k8s.io/client-go`, `staging/src/k8s.io/kubectl`, alongside `pkg`, `test` and `cmd`.

Source: `results/phase0/areas_and_ownership.json`, `results/phase0/adaptive_area_rule.json`.

---

## 7. Ownership: CODEOWNERS is almost never there

| repo | CODEOWNERS at a standard path | what it covers | per-directory `OWNERS` files |
|---|---|---|---|
| `Kludex/starlette` | none | — | 0 |
| `optuna/optuna` | `.github/CODEOWNERS` | 1 rule, 1 owner, pattern `.github/` | 0 |
| `kubernetes/kubernetes` | none | — | **593** |

Across all three repositories, CODEOWNERS supplies owner evidence for **zero contribution areas**.
Optuna's file is 30 bytes and covers only `.github/`, which is not somewhere a newcomer contributes.

Kubernetes expresses ownership through 593 per-directory `OWNERS` files (the prow convention), which
map onto directory areas more precisely than a root CODEOWNERS ever would. It also contains four
`CODEOWNERS` files **inside `vendor/`**, belonging to vendored third-party projects; a naive search
for `**/CODEOWNERS` would attribute other projects' maintainers to this repository.

**Decisions.**
- Keep the rule that nobody is called a maintainer without file evidence.
- Read CODEOWNERS only from the three standard locations (`CODEOWNERS`, `.github/CODEOWNERS`,
  `docs/CODEOWNERS`). Never glob the tree for it.
- Also parse per-directory `OWNERS` files, and label the source on the report — "listed in
  CODEOWNERS" or "listed in OWNERS" — so the evidence is visible and never merged into one claim.
- Expect the common case to be no ownership data at all, and render that as an empty state rather
  than guessing from commit counts. Contributor and reviewer **counts** are still shown, because
  those are measured facts and make no claim about authority.
