"""One PR as the metrics see it: a small record built from a GraphQL node.

Only human authors are kept (bots, deleted accounts and other non-users are
dropped before sampling). A record holds no file paths: only how many changed files
fall in each current area, the two response times, and who reviewed.

Response times use the first 20 reviews and 30 comments. When no human answer is
among them and GitHub says more exist, the times are marked unknown
(`response_times_complete` is False) rather than guessed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from repocompass.areas import area_of, drop_excluded
from repocompass.config import Settings
from repocompass.github import GitHubError

__all__ = [
    "PrRecord",
    "created_at",
    "human_login",
    "parse_pr",
    "pr_areas",
    "record_from_json",
    "record_to_json",
]


TIME_FIELDS = (
    "created_at",
    "merged_at",
    "closed_at",
    "first_formal_review_at",
    "first_human_response_at",
)


@dataclass(frozen=True)
class PrRecord:
    number: int
    author: str  # only human authors are kept
    association: str | None
    created_at: datetime
    merged_at: datetime | None
    closed_at: datetime | None
    state: str
    merged: bool
    changed_files: int
    files_complete: bool
    area_files: dict[str, int]
    first_formal_review_at: datetime | None
    first_human_response_at: datetime | None
    # False when no human answer was in the fetched slice and the slice was cut short
    response_times_complete: bool
    reviewers: tuple[str, ...]  # one entry per review by someone other than the author
    is_newcomer: bool = False


def _time(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def created_at(node: dict[str, Any]) -> datetime:
    created = _time(node.get("createdAt"))
    if created is None:
        raise GitHubError(f"PR #{node.get('number')} has no creation time")
    return created


def human_login(actor: dict[str, Any] | None, settings: Settings) -> str | None:
    """The login of a real user, or None for bots, deleted accounts and non-users."""
    if not actor or actor.get("__typename") != "User":
        return None
    login = actor.get("login")
    return None if settings.is_bot_login(login) else login


def _has_more(connection: dict[str, Any]) -> bool:
    return bool((connection.get("pageInfo") or {}).get("hasNextPage"))


def pr_areas(area_files: dict[str, int]) -> list[str]:
    """The area with the most changed files; ties count for each tied area."""
    if not area_files:
        return []
    most = max(area_files.values())
    return sorted(area for area, n in area_files.items() if n == most)


def parse_pr(
    node: dict[str, Any],
    paths: Iterable[str],
    depths: dict[str, int],
    areas: set[str],
    settings: Settings,
    *,
    files_complete: bool = True,
) -> PrRecord:
    author = human_login(node.get("author"), settings)
    if author is None:
        raise GitHubError(f"PR #{node.get('number')} has no human author")
    created = created_at(node)

    area_files: Counter[str] = Counter()
    for path in drop_excluded(paths, settings.excluded_dirs):
        area = area_of(path, depths)
        if area in areas:
            area_files[area] += 1

    def by_others(items: list[dict[str, Any]], key: str) -> list[tuple[datetime, str]]:
        out = []
        for item in items:
            login = human_login(item.get("author"), settings)
            when = _time(item.get(key))
            if login and when and login != author:
                out.append((when, login))
        return sorted(out)

    review_conn = node.get("reviews") or {}
    comment_conn = node.get("comments") or {}
    reviews = by_others(review_conn.get("nodes") or [], "submittedAt")
    comments = by_others(comment_conn.get("nodes") or [], "createdAt")
    # an answer is known if one was seen, or if the slice held every item
    review_known = bool(reviews) or not _has_more(review_conn)
    comment_known = bool(comments) or not _has_more(comment_conn)
    complete = review_known and comment_known
    first_review = reviews[0][0] if reviews else None
    first_response = min([t for t, _ in reviews[:1] + comments[:1]], default=None)
    if not complete:
        first_response = None

    return PrRecord(
        number=node["number"],
        author=author,
        association=node.get("authorAssociation"),
        created_at=created,
        merged_at=_time(node.get("mergedAt")),
        closed_at=_time(node.get("closedAt")),
        state=node["state"],
        merged=bool(node.get("merged")),
        changed_files=int(node.get("changedFiles") or 0),
        files_complete=files_complete,
        area_files=dict(area_files),
        first_formal_review_at=first_review,
        first_human_response_at=first_response,
        response_times_complete=complete,
        reviewers=tuple(login for _, login in reviews),
    )


def record_to_json(record: PrRecord) -> dict[str, Any]:
    out = asdict(record)
    for key, value in out.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
    out["reviewers"] = list(record.reviewers)
    return out


def record_from_json(data: dict[str, Any]) -> PrRecord:
    values = dict(data)
    for key in TIME_FIELDS:
        values[key] = _time(values[key])
    values["reviewers"] = tuple(values["reviewers"])
    return PrRecord(**values)
