#!/usr/bin/env python3
"""Generate data/llm_math_export/solution_progress/index.json from PDF folders."""

import json
import pathlib
from typing import Any, Optional

WEBSITE_ROOT = pathlib.Path("data/llm_math_export")
ATTEMPTS_ROOT = WEBSITE_ROOT / "solution_progress"
CLASSIFICATIONS_PATH = ATTEMPTS_ROOT / "solution_classifications.json"
VALID_CLASSIFICATIONS = {"direct_proof", "counterexample"}


def main() -> None:
    live_problem_ids = _load_live_problem_ids(WEBSITE_ROOT / "index.json")
    classifications = _load_classifications(CLASSIFICATIONS_PATH)
    manifest = _build_manifest(live_problem_ids, classifications)
    _write_json(ATTEMPTS_ROOT / "index.json", manifest)
    classified = sum(
        1
        for row in manifest["problems"].values()
        for sol in row["solutions"]
        if sol.get("classification")
    )
    print(
        f"Wrote {ATTEMPTS_ROOT / 'index.json'} "
        f"({manifest['counts']['problems_with_progress']} problems, "
        f"{manifest['counts']['solution_pdfs']} solution PDFs, "
        f"{manifest['counts']['partial_progress_pdfs']} partial PDFs, "
        f"{classified} classified solutions).",
    )


def _build_manifest(
    live_problem_ids: set[str],
    classifications: dict[str, str],
) -> dict[str, Any]:
    ATTEMPTS_ROOT.mkdir(parents=True, exist_ok=True)
    by_problem: dict[str, dict[str, list[dict[str, str]]]] = {}
    for problem_dir in sorted(p for p in ATTEMPTS_ROOT.iterdir() if p.is_dir()):
        problem_id = problem_dir.name
        if problem_id not in live_problem_ids:
            continue
        solutions = _pdf_entries(
            problem_dir / "solutions",
            problem_id,
            "solution",
            classifications.get(problem_id),
        )
        partial_progress = _pdf_entries(
            problem_dir / "partial_progress",
            problem_id,
            "partial_progress",
            None,
        )
        if solutions or partial_progress:
            by_problem[problem_id] = {
                "solutions": solutions,
                "partial_progress": partial_progress,
            }
    return {
        "schema_version": 1,
        "base_path": "data/llm_math_export/solution_progress",
        "counts": {
            "problems_with_progress": len(by_problem),
            "solution_pdfs": sum(len(row["solutions"]) for row in by_problem.values()),
            "partial_progress_pdfs": sum(len(row["partial_progress"]) for row in by_problem.values()),
        },
        "problems": by_problem,
    }


def _pdf_entries(
    path: pathlib.Path,
    problem_id: str,
    kind: str,
    classification: Optional[str],
) -> list[dict[str, str]]:
    if not path.exists():
        return []
    entries: list[dict[str, str]] = []
    for pdf in sorted(path.glob("*.pdf")):
        entry: dict[str, str] = {
            "kind": kind,
            "label": _label_from_filename(pdf.name, kind),
            "path": f"data/llm_math_export/solution_progress/{problem_id}/{path.name}/{pdf.name}",
            "filename": pdf.name,
        }
        if kind == "solution" and classification:
            entry["classification"] = classification
        entries.append(entry)
    return entries


def _load_classifications(path: pathlib.Path) -> dict[str, str]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("classifications", {}) if isinstance(payload, dict) else {}
    if not isinstance(raw, dict):
        raise RuntimeError(f"Invalid classifications payload: {path}")
    out: dict[str, str] = {}
    for problem_id, value in raw.items():
        label = str(value).strip()
        if label not in VALID_CLASSIFICATIONS:
            raise RuntimeError(
                f"Invalid classification for {problem_id!r}: {value!r} "
                f"(expected one of {sorted(VALID_CLASSIFICATIONS)})",
            )
        out[str(problem_id)] = label
    return out


def _label_from_filename(filename: str, kind: str) -> str:
    stem = pathlib.Path(filename).stem
    if stem.isdigit():
        if kind == "solution":
            return f"Solution #{int(stem)} (PDF)"
        return f"Partial progress #{int(stem)} (PDF)"
    parts = stem.split("_", 1)
    if len(parts) == 2 and parts[0].isdigit():
        if kind == "solution":
            return f"Solution #{int(parts[0])} (PDF)"
        return f"Partial progress #{int(parts[0])} (PDF)"
    return stem.replace("_", " ")


def _load_live_problem_ids(index_path: pathlib.Path) -> set[str]:
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("problems"), list):
        raise RuntimeError(f"Invalid website index: {index_path}")
    problem_ids: set[str] = set()
    for row in payload["problems"]:
        if not isinstance(row, dict) or "problem_id" not in row:
            raise RuntimeError(f"Invalid problem row in {index_path}")
        problem_ids.add(str(row["problem_id"]))
    return problem_ids


def _write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
