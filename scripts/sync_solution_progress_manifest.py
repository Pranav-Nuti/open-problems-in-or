#!/usr/bin/env python3
"""Generate data/llm_math_export/solution_progress/index.json from PDF folders."""

import json
import pathlib
from typing import Any

WEBSITE_ROOT = pathlib.Path("data/llm_math_export")
ATTEMPTS_ROOT = WEBSITE_ROOT / "solution_progress"


def main() -> None:
    live_problem_ids = _load_live_problem_ids(WEBSITE_ROOT / "index.json")
    manifest = _build_manifest(live_problem_ids)
    _write_json(ATTEMPTS_ROOT / "index.json", manifest)
    print(
        f"Wrote {ATTEMPTS_ROOT / 'index.json'} "
        f"({manifest['counts']['problems_with_progress']} problems, "
        f"{manifest['counts']['solution_pdfs']} solution PDFs, "
        f"{manifest['counts']['partial_progress_pdfs']} partial PDFs).",
    )


def _build_manifest(live_problem_ids: set[str]) -> dict[str, Any]:
    ATTEMPTS_ROOT.mkdir(parents=True, exist_ok=True)
    by_problem: dict[str, dict[str, list[dict[str, str]]]] = {}
    for problem_dir in sorted(p for p in ATTEMPTS_ROOT.iterdir() if p.is_dir()):
        problem_id = problem_dir.name
        if problem_id not in live_problem_ids:
            continue
        solutions = _pdf_entries(problem_dir / "solutions", problem_id, "solution")
        partial_progress = _pdf_entries(problem_dir / "partial_progress", problem_id, "partial_progress")
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


def _pdf_entries(path: pathlib.Path, problem_id: str, kind: str) -> list[dict[str, str]]:
    if not path.exists():
        return []
    entries: list[dict[str, str]] = []
    for pdf in sorted(path.glob("*.pdf")):
        entries.append(
            {
                "kind": kind,
                "label": _label_from_filename(pdf.name, kind),
                "path": f"data/llm_math_export/solution_progress/{problem_id}/{path.name}/{pdf.name}",
                "filename": pdf.name,
            },
        )
    return entries


def _label_from_filename(filename: str, kind: str) -> str:
    stem = pathlib.Path(filename).stem
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
