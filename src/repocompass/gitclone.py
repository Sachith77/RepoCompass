"""The git CLI: blobless clones, the file tree, and commit history.

Clones use `--filter=blob:none --no-checkout`, so no file contents are downloaded:
the tree and commit history are enough for areas and activity (ADR-0001).

Every command reads from `origin/<default branch>` rather than the local branch,
because `git fetch` moves the remote-tracking branch, not the local one that a
no-checkout clone never updates.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from repocompass.activity import Commit

__all__ = [
    "GitError",
    "clone_or_update",
    "clone_path",
    "list_files",
    "log_args",
    "parse_log",
    "read_commits",
]

RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"
# Committer date (%cI) decides the window, so a rebased PR is dated when it landed.
# Raw author name and email (%an/%ae): a no-checkout clone has no .mailmap to apply.
LOG_FORMAT = "--format=%x1e%H%x1f%cI%x1f%an%x1f%ae"


class GitError(RuntimeError):
    """A git command failed or printed something unexpected."""


def _git(args: list[str], cwd: Path | None = None) -> str:
    # quotePath=false prints non-ASCII paths as-is instead of escaping them;
    # GIT_TERMINAL_PROMPT=0 makes a missing repository fail instead of asking for a password.
    proc = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip().splitlines()[-1:] or ["no error output"]
        raise GitError(f"git {args[0]} failed: {detail[0]}")
    return proc.stdout


def clone_path(clone_dir: Path, canonical_slug: str) -> Path:
    return clone_dir / canonical_slug.replace("/", "__")


def clone_or_update(url: str, dest: Path) -> None:
    """Clone without blobs or checkout, or fetch if the clone already exists."""
    if dest.exists():
        if not (dest / ".git").is_dir():
            raise GitError(f"{dest} exists but is not a git clone")
        _git(["fetch", "--prune", "origin"], cwd=dest)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    _git(["clone", "--filter=blob:none", "--no-checkout", url, str(dest)])


def list_files(repo: Path, rev: str) -> list[str]:
    """Every file path in the tree at `rev`."""
    out = _git(["ls-tree", "-r", "--name-only", rev], cwd=repo)
    return [line for line in out.splitlines() if line]


def log_args(rev: str, since: datetime) -> list[str]:
    # --no-renames matters: rename detection compares file contents, which makes a
    # blobless clone download blobs on demand. A rename then shows as a delete plus an
    # add, and the deleted path simply belongs to no current area.
    return [
        "log",
        rev,
        "--no-merges",
        "--no-renames",
        f"--since={since.isoformat()}",
        LOG_FORMAT,
        "--name-only",
    ]


def parse_log(text: str) -> list[Commit]:
    """Parse `git log` output written with LOG_FORMAT and --name-only."""
    commits: list[Commit] = []
    for record in text.split(RECORD_SEP):
        if not record.strip():
            continue
        header, *path_lines = record.splitlines()
        fields = header.split(FIELD_SEP)
        if len(fields) != 4:
            raise GitError("unexpected git log header")
        sha, committed, name, email = fields
        commits.append(
            Commit(
                sha=sha,
                committed_at=datetime.fromisoformat(committed),
                author_name=name,
                author_email=email,
                paths=tuple(line for line in path_lines if line),
            )
        )
    return commits


def read_commits(repo: Path, rev: str, since: datetime) -> list[Commit]:
    """Non-merge commits on `rev` committed since `since`, with the paths each changed."""
    return parse_log(_git(log_args(rev, since), cwd=repo))
