# ADR-0001: Blobless no-checkout clone for history, GraphQL for PR data

Status: accepted, 2026-11-03

Chose a `git clone --filter=blob:none --no-checkout` plus the GitHub GraphQL API over cloning fully,
or over using the REST API for everything.

Why: the clone gives commit history and changed file paths with no API cost and no file contents,
measured at 2.0 s / 5.1 s / 79.3 s and 1.9 / 14.7 / 254.8 MiB for the three reference repositories.
GraphQL then supplies PR metadata, file paths, reviews and comments in one request per page at 1–2
points, where REST would need separate calls per PR for files and reviews. Fetching `files(first: 100)`
inline costs one extra point per page, so a cheap-metadata-then-files two-pass design was rejected as
complexity for no saving. A full clone would download blobs we never read.

Trade-off: two data sources to keep consistent, and the clone needs local disk (254.8 MiB for
kubernetes).

Would revisit if: GraphQL point costs rose sharply, or if file-content analysis entered scope, which
would make a full clone worth its cost.
