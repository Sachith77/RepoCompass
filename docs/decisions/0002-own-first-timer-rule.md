# ADR-0002: Define first-time contributor ourselves, not from authorAssociation

Status: accepted, 2026-11-03

Chose our own rule — *no merged PR by this author in this repository was created before this one*,
over all repository history — over GitHub's `authorAssociation` field.

Why: the two disagreed on 9 of 60 sampled PRs, and 8 of those 9 failed the same way.
`authorAssociation` is evaluated **when you query**, not when the PR was opened, so an author whose
first PR merged is now reported as `CONTRIBUTOR` and their genuinely-first PR stops counting as a
newcomer PR. That bias is correlated with the outcome being measured: successful first PRs leave the
newcomer pool while rejected ones stay in it, which would push the newcomer merge rate down. Separately,
`NONE` means "no association with the repo", not "first-timer" — one kubernetes PR had an author still
reported as `NONE` who already had an earlier merged PR.

Cost: one `search` query per distinct author, batched 20 per request with GraphQL aliases, taking
`optuna/optuna` from 148 requests to 8.

Trade-off: the lookback sees only PR history, so contributions made by direct push or before a GitHub
migration are invisible and such authors count as newcomers. Documented on the method page.

Would revisit if: GitHub exposed a point-in-time association field.
