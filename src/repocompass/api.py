"""The HTTP API: one FastAPI service that reads Postgres and queues jobs.

It never calls GitHub; every network call happens in the worker (ADR-0005). So
POST /analyze only checks that the text is a github.com owner/repo; whether the
repository exists and is public is found out by the worker, and a job that fails
for that reason says so in GET /jobs/{id}.

    POST /analyze {"repo_url": ...}   the stored report itself, or a queued job (202)
    GET  /repos                       analysed repositories
    GET  /repos/{owner}/{repo}/report the full report
    GET  /jobs/{id}                   progress, with the areas map once the git stage is done
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from repocompass import __version__
from repocompass.config import Settings
from repocompass.db import DatabaseError
from repocompass.github import GitHubError, parse_repo_slug
from repocompass.jobs import enqueue_job, get_job
from repocompass.report import OutdatedReport, list_repos, load_report

__all__ = ["create_app"]


class AnalyzeRequest(BaseModel):
    repo_url: str


def _report_url(slug: str) -> str:
    return f"/repos/{slug}/report"


def _areas_preview(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """The git stage's activity rows from a checkpoint, in the report's areas-map shape."""
    if rows is None:
        return None
    return [
        {
            "area": r["area"],
            "commits_90d": r["commits_recent"],
            "commits_12mo": r["commits_window"],
            "commit_authors_12mo": r["authors_window"],
            "activity_band": r["band"],
        }
        for r in rows
    ]


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="RepoCompass", version=__version__)
    # only the local web pages may call the API from a browser
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.web_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(DatabaseError)
    def database_down(request: Request, exc: DatabaseError) -> JSONResponse:
        # the message is already scrubbed, but a client needs no database detail at all
        return JSONResponse(status_code=503, content={"detail": "database unavailable"})

    @app.post("/analyze")
    def analyze(body: AnalyzeRequest, response: Response) -> dict[str, Any]:
        try:
            owner, name = parse_repo_slug(body.repo_url)
        except GitHubError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        try:
            stored = load_report(settings, owner, name)
        except OutdatedReport:
            stored = None  # an analysis from an older schema: simply analyse it again
        if stored is not None:
            slug = stored["repo"]["canonical_slug"]
            return {"status": "cached", "report_url": _report_url(slug), "report": stored}
        slug = f"{owner}/{name}"
        job_id, state = enqueue_job(settings.database_url, slug)
        response.status_code = 202
        return {
            "status": state,
            "requested_slug": slug,
            "job_id": job_id,
            "job_url": f"/jobs/{job_id}",
        }

    @app.get("/repos")
    def repos() -> dict[str, Any]:
        return {"repos": list_repos(settings)}

    @app.get("/repos/{owner}/{repo}/report")
    def report(owner: str, repo: str) -> dict[str, Any]:
        try:
            owner, repo = parse_repo_slug(f"{owner}/{repo}")
        except GitHubError:
            raise HTTPException(status_code=404, detail="not a repository name") from None
        try:
            found = load_report(settings, owner, repo)
        except OutdatedReport as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        if found is None:
            raise HTTPException(status_code=404, detail="this repository has not been analysed")
        return found

    @app.get("/jobs/{job_id}")
    def job(job_id: int) -> dict[str, Any]:
        found = get_job(settings.database_url, job_id)
        if found is None:
            raise HTTPException(status_code=404, detail="no such job")
        preview = found.pop("areas_preview")
        stored, from_checkpoint = found.pop("canonical_slug"), found.pop("checkpoint_slug")
        slug = stored or from_checkpoint
        found["report_url"] = _report_url(slug) if found["state"] == "done" and slug else None
        found["areas_map"] = None if found["state"] == "done" else _areas_preview(preview)
        return found

    return app
