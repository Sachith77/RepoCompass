# ADR-0003: Report bands against the repo rate, not a 1-2-3 ranking

Status: accepted, 2026-11-03

Chose banding — compare each area's 95% Wilson interval with the repository-wide mature newcomer merge
rate, and label it above / below / no clear difference — over ordering areas by their Wilson lower
bound.

Why: the Wilson lower bound is the right statistic, but at the sample sizes actually available it does
not support an ordering. Measured on `optuna/optuna`, qualifying areas had 12–26 mature newcomer PRs
and intervals roughly 0.4 wide: `optuna/visualization` (0.357–0.802), `optuna/samplers` (0.342–0.742)
and `optuna/pruners` (0.291–0.768) are statistically indistinguishable. Printing them as 1, 2, 3 would
assert a precision the data does not contain. What the data *does* support is the extremes:
`optuna/visualization` against `optuna/study` (0.062–0.335) do not overlap, and `docs` (0.317–0.599)
against `tests` (0.116–0.239) do not overlap.

Consequence: validation changes shape too. Instead of a rank correlation it asks whether areas banded
"above repo average" before a cutoff stayed above the repo rate after it.

Trade-off: a banded report is less immediately satisfying than a leaderboard, and many areas will land
in "no clear difference".

Would revisit if: sample sizes per area grew enough that intervals stopped overlapping — which would
need several times more newcomer PRs per area than any reference repository currently provides.
