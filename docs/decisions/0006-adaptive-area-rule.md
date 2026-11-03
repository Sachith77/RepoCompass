# ADR-0006: Fit area depth per repository, and exclude vendored trees and root files

Status: accepted, 2026-11-03

Chose an adaptive rule — group files by top directory; if one group holds more than a quarter of the
files, split that group one level deeper; repeat up to four levels — over the brief's original fixed
"one or two directory levels".

Why: two levels does not fit real layouts. Measured, one level left `optuna/optuna` with its largest
area at 46.5% and `kubernetes/kubernetes` at 64.9%. Going to two levels fixed optuna (26.4%) and did
essentially nothing for kubernetes (64.8%), because `staging/` contains `staging/src/k8s.io/<package>/`
— splitting once just renames the giant area from `staging` (16,942 files) to `staging/src` (16,935).
The adaptive rule produced 7 / 32 / 50 areas with largest shares of 24.5% / 15.5% / 18.5%, and gave
kubernetes areas a newcomer would recognise: `staging/src/k8s.io/client-go`, `.../kubectl`, `.../api`.

Two exclusions come with it. Vendored and generated trees (`vendor`, `third_party`, `node_modules`, and
a configurable list) are dropped before the rule is fitted — kubernetes' `vendor/` also contained four
third-party `CODEOWNERS` files that would have attributed other projects' maintainers to it. And **root
files are excluded from banded areas**: `(root file)` otherwise qualified on two of three reference
repositories (n=14 and n=12), but `README.md` and `pyproject.toml` are not a place to start. They are
still counted in activity, just never offered as an area.

Trade-off: the rule is per-repository, so the report must print which depth it used.

Would revisit if: a repository's meaningful areas were not directories at all — a monorepo keyed on
package manifests, say.
