"""Tests for the adaptive area rule (ADR-0006)."""

from __future__ import annotations

from repocompass.areas import area_names, area_of, drop_excluded, fit_area_depths


def _files(prefix: str, n: int) -> list[str]:
    return [f"{prefix}/f{i}.py" for i in range(n)]


def test_root_files_belong_to_no_area() -> None:
    assert area_of("README.md", {}) is None
    assert area_of("docs/index.md", {}) == "docs"


def test_deepened_root_uses_more_levels_but_never_the_file_name() -> None:
    depths = {"optuna": 2}
    assert area_of("optuna/samplers/tpe.py", depths) == "optuna/samplers"
    # a file directly inside the deepened directory stays in the directory itself
    assert area_of("optuna/__init__.py", depths) == "optuna"
    # other roots are unaffected
    assert area_of("docs/source/conf.py", depths) == "docs"


def test_excluded_dirs_are_dropped_at_the_top_level_only() -> None:
    paths = ["vendor/a.go", "pkg/vendor/b.go", "node_modules/x.js", "pkg/c.go"]
    assert drop_excluded(paths, ("vendor", "node_modules")) == ["pkg/vendor/b.go", "pkg/c.go"]


def test_no_split_when_no_area_is_oversized() -> None:
    files = _files("a", 25) + _files("b", 25) + _files("c", 25) + _files("d", 25)
    assert fit_area_depths(files, threshold_share=0.25, max_depth=4) == {}


def test_oversized_area_is_split_one_level_deeper() -> None:
    files = (
        _files("pkg/core", 20)
        + _files("pkg/cli", 20)
        + _files("pkg/web", 20)
        + _files("docs", 20)
        + _files("tests", 20)
    )
    depths = fit_area_depths(files, threshold_share=0.25, max_depth=4)
    assert depths == {"pkg": 2}
    assert area_names(files, depths) == ["docs", "pkg/cli", "pkg/core", "pkg/web", "tests"]


def test_keeps_splitting_through_single_child_directories() -> None:
    """The kubernetes case: staging/src/k8s.io/<package>/ needs four levels."""
    files = (
        _files("staging/src/k8s.io/api", 30)
        + _files("staging/src/k8s.io/client-go", 30)
        + _files("staging/src/k8s.io/kubectl", 30)
        + _files("pkg", 30)
        + _files("test", 30)
    )
    depths = fit_area_depths(files, threshold_share=0.25, max_depth=4)
    assert depths == {"staging": 4}
    assert "staging/src/k8s.io/client-go" in area_names(files, depths)


def test_stops_at_max_depth() -> None:
    files = _files("a/b/c/d/e/f", 90) + _files("z", 10)
    depths = fit_area_depths(files, threshold_share=0.25, max_depth=3)
    assert depths == {"a": 3}


def test_stops_when_the_largest_group_is_root_files() -> None:
    files = [f"file{i}.txt" for i in range(80)] + _files("src", 20)
    assert fit_area_depths(files, threshold_share=0.25, max_depth=4) == {}


def test_area_names_never_include_root_files() -> None:
    files = ["README.md", "pyproject.toml", *_files("src", 3)]
    assert area_names(files, {}) == ["src"]


def test_empty_tree_has_no_areas() -> None:
    assert fit_area_depths([], threshold_share=0.25, max_depth=4) == {}
    assert area_names([], {}) == []
