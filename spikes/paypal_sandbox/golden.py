"""Read-only access to the golden dataset. Only development cases may be seeded into the sandbox."""
from __future__ import annotations

import json
from pathlib import Path

SEEDABLE_SPLITS = {"development"}


def load_case(golden_dir: Path, case_id: str) -> dict:
    for split_file in sorted(golden_dir.glob("*/cases.jsonl")):
        with split_file.open(encoding="utf-8") as fh:
            for line in fh:
                case = json.loads(line)
                if case["case_id"] == case_id:
                    return case
    raise SystemExit(f"Case {case_id} not found under {golden_dir}")


def load_seedable_case(golden_dir: Path, case_id: str) -> dict:
    case = load_case(golden_dir, case_id)
    if case.get("split") not in SEEDABLE_SPLITS:
        raise SystemExit(
            f"Refusing to send {case_id} to the sandbox: split={case.get('split')!r}. "
            "Calibration and holdout cases stay offline."
        )
    if case.get("synthetic") is not True:
        raise SystemExit(f"Refusing to send {case_id}: not marked synthetic.")
    return case
