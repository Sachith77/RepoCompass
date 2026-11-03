# ADR-0005: A jobs table and one worker, not synchronous analysis

Status: accepted, 2026-11-03

Chose a `jobs` table with one worker process claiming rows via `SELECT ... FOR UPDATE SKIP LOCKED`
over running an analysis inside the HTTP request.

Why: measured cold analysis times were 81 s (small), 56 s (medium) and 986 s / 16.4 min (huge). The
brief's own threshold was "under about 60 seconds, run it synchronously", and two of three reference
repositories exceed it — including the *small* one, because cost tracks PR count and author diversity
rather than repository size. No HTTP request should hold a connection for 16 minutes. Separately,
resumability turned out to be mandatory rather than nice: the first long Phase 0 run died when GitHub
closed the connection mid-pagination, and because the script saved only at the end it discarded two
already-completed repositories. A job row gives somewhere to checkpoint. Postgres `SKIP LOCKED` avoids
adding Redis or Celery for a single worker.

Trade-off: the client must poll `GET /jobs/{id}`, and there is now a process to keep running.

Would revisit if: analysis dropped reliably under a few seconds, or if more than one worker were needed,
at which point the claim query still works but backpressure would need thought.
