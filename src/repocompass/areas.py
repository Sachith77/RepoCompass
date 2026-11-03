"""The area rule: which directory a file belongs to (ADR-0006).

In plain words: group files by their top directory. If one group holds more than a
quarter of the files, split that group one level deeper. Repeat until no group is
oversized, up to four levels. The depth chosen for each top directory is stored with
the report so it can say which rule it used.

Root files (README.md, pyproject.toml) belong to no area: they are not a place to
start, and they add nothing to any area's activity counts. Vendored and generated
trees are dropped before the rule is fitted; the excluded names match top-level
directories only.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

__all__ = ["area_names", "area_of", "drop_excluded", "fit_area_depths"]


def drop_excluded(paths: Iterable[str], excluded_dirs: Iterable[str]) -> list[str]:
    """Remove paths whose top-level directory is excluded (vendor, node_modules, ...)."""
    excluded = set(excluded_dirs)
    return [p for p in paths if p.split("/", 1)[0] not in excluded]


def area_of(path: str, depths: dict[str, int]) -> str | None:
    """The area of one file, or None for a file in the repository root.

    `depths` maps a top-level directory to how many directory levels its areas use;
    directories not listed use one level. A file never becomes its own area: a file
    directly inside a deepened directory stays in that directory.
    """
    parts = path.split("/")
    if len(parts) == 1:
        return None
    depth = min(depths.get(parts[0], 1), len(parts) - 1)
    return "/".join(parts[:depth])


def fit_area_depths(files: list[str], threshold_share: float, max_depth: int) -> dict[str, int]:
    """Deepen the largest area until none holds more than `threshold_share` of files.

    Each step deepens the top-level directory that owns the largest area by one
    level. It stops when the largest group is small enough, when the largest group
    is the root files (which cannot be split), or when that directory is already at
    `max_depth`. Every step raises some depth towards `max_depth`, so it always ends.
    """
    depths: dict[str, int] = {}
    while True:
        counts = Counter(area_of(f, depths) for f in files)
        total = sum(counts.values())
        if not total:
            return depths
        largest, n = counts.most_common(1)[0]
        if largest is None or n / total <= threshold_share:
            return depths
        root = largest.split("/", 1)[0]
        current = depths.get(root, 1)
        if current >= max_depth:
            return depths
        depths[root] = current + 1


def area_names(files: Iterable[str], depths: dict[str, int]) -> list[str]:
    """Sorted areas present in a file list. Root files are not an area."""
    return sorted({a for f in files if (a := area_of(f, depths)) is not None})
