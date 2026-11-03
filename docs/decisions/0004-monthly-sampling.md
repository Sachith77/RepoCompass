# ADR-0004: Sample up to 250 PRs per month, not the most recent 3,000

Status: accepted, 2026-11-03

Chose a per-calendar-month cap of 250 sampled PRs across the 12-month window over a flat cap of the
most recent 3,000 PRs.

Why: a flat recency cap silently changes what "the last 12 months" means. Measured on
`kubernetes/kubernetes`, which had 6,616 PRs in the window, the 3,000 cap retained only PRs created on
or after 2026-06-22 — **134 days, 37% of the intended window**. The 30-day maturity rule then removes
the newest month, leaving about 104 usable days, which is why only 313 of 735 newcomer PRs survived.
A report labelled "last 12 months" built on 134 days of data is simply false. Monthly caps keep every
month represented, so seasonality and release cycles are not truncated away, and the sample stays
spread across the window.

Requirement this creates: total PRs, sampled PRs and per-month counts are recorded per report, and the
report is labelled "sampled" whenever any month was capped.

Trade-off: more bookkeeping than one number, and a busy month is still under-sampled — just not
invisibly.

Would revisit if: per-month volumes exceeded the cap so widely that 250 stopped being representative,
in which case the cap should scale with the month's volume rather than being flat.
