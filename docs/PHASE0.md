# Phase 0 checklist: evidence, not code (about one working day)
Label every number as measured or estimated. Measurement scripts stay in spikes/.

1. Pick 3 test repos: one small, one medium (for example optuna/optuna or pydantic/pydantic),
   one huge (for example kubernetes/kubernetes).
2. Clone cost: time and disk size of a clone with --filter=blob:none --no-checkout for each; time to extract
   12 months of commits with changed file paths.
3. GraphQL cost: count PRs in the last 12 months per repo and compare with the 3,000 cap; for page sizes 25
   and 50 with the fields we need, measure points per page, seconds per page and any timeouts. Count PRs with
   more than 100 changed files and the extra requests they need. Estimate total time and points per repo,
   and how many medium repos one token can analyze per hour.
4. First-time contributor: on 20 PRs per repo, compare authorAssociation with our own "no merged PR before
   this one" check using full PR history; measure the cost of that lookback; recommend a definition and
   state its limitation.
5. Reviews: per repo, how many PRs have a formal review vs only comments (for example /lgtm-style approvals);
   recommend how the report should present the two response times.
6. Starter issues: on 20 open labelled issues per repo, check which signals exist (assignees, linked PRs via
   timeline events, claim comments); note the phrase patterns you actually see.
7. Areas and ownership: inspect the 3 layouts and propose the area rule (one or two directory levels) with
   examples; record whether each repo has CODEOWNERS or a maintainers file.
8. Workload decision input: from items 2-3, estimate full-analysis time for a medium repo, and say whether
   a queue + worker is needed or a synchronous run is enough.
9. Hosting and storage: compare a Hugging Face Spaces worker with a GitHub Actions worker for cloning and
   processing (limits, cold start, disk); estimate database size per analyzed repo and compare with current
   Neon and Supabase free tiers. Record source URLs and the date checked.
10. Local setup on my Windows machine: check whether Docker Desktop is available for Postgres. If not,
    recommend a free Neon or Supabase database for development.

Output: docs/00-feasibility.md and docs/data/github_signals.md. Then STOP.
