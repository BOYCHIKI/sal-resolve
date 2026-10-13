"""Score the pipeline against the golden dataset.

    python -m app.agent.evaluate                      # development split, baseline roles
    python -m app.agent.evaluate --split calibration
    python -m app.agent.evaluate --split holdout --final   # only once rules/prompts are frozen

The pipeline sees only the dispute and evidence text; ground_truth is used for scoring only.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agent.models import AnalysisResult, CaseInput, Document, Line
from app.agent.pipeline import analyze
from app.agent.roles import ReadAllPlanner, RuleExtractor, TemplateDrafter
from app.agent.validation import PROHIBITED_RE, _appears
from app.config import REPO_ROOT

GOLDEN_DIR = REPO_ROOT / "data" / "golden" / "v1.0.0"


def load_cases(split: str, golden_dir: Path = GOLDEN_DIR) -> list[dict[str, Any]]:
    path = golden_dir / split / "cases.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def to_case_input(case: dict[str, Any]) -> CaseInput:
    d = case["dispute"]
    docs = tuple(Document(e["evidence_id"], e["type"], tuple(Line(l["line"], l["text"]) for l in e["content_lines"]))
                 for e in case["evidence"])
    return CaseInput(case["case_id"], d["reason"], d["amount"]["value"], d["amount"]["currency"], (), docs)


@dataclass
class Score:
    facts_expected: int = 0
    facts_found: int = 0          # GT facts recovered (field + exact value)
    facts_predicted: int = 0      # predicted facts on GT fields
    facts_correct: int = 0        # predicted facts on GT fields that are right
    provenance_ok: int = 0        # recovered facts citing the GT source line
    missing_tp: int = 0
    missing_fp: int = 0
    missing_fn: int = 0
    conflict_tp: int = 0
    conflict_fp: int = 0
    conflict_fn: int = 0
    review_correct: int = 0
    claims: int = 0
    unsupported_claims: int = 0   # kept claims not traceable to a GT-supported fact value
    prohibited_claims: int = 0
    cases: int = 0
    errors: list[str] = field(default_factory=list)

    def add(self, other: "Score") -> None:
        for k, v in vars(other).items():
            if isinstance(v, int):
                setattr(self, k, getattr(self, k) + v)
            else:
                getattr(self, k).extend(v)


def _ratio(a: int, b: int) -> str:
    return f"{a / b:.2f}" if b else "n/a"


def score_case(case: dict[str, Any], result: AnalysisResult) -> Score:
    gt = case["ground_truth"]
    s = Score(cases=1)
    expected = {(f["field"], str(f["value"])): f["source_ref"] for f in gt["supported_facts"]}
    gt_fields = {f for f, _ in expected}
    predicted = {(f.field, f.value): f.source for f in result.facts
                 if f.status != "rejected" and f.field in gt_fields}
    s.facts_expected, s.facts_predicted = len(expected), len(predicted)
    s.facts_correct = s.facts_found = len(expected.keys() & predicted.keys())
    s.provenance_ok = sum(1 for k in expected.keys() & predicted.keys()
                          if (predicted[k].evidence_id, predicted[k].line) ==
                          (expected[k]["evidence_id"], expected[k]["line"]))

    gm, pm = set(gt["missing_evidence"]), set(result.missing)
    s.missing_tp, s.missing_fp, s.missing_fn = len(gm & pm), len(pm - gm), len(gm - pm)
    gc = {c["field"] for c in gt["conflicts"]}
    pc = {c.field for c in result.conflicts}
    s.conflict_tp, s.conflict_fp, s.conflict_fn = len(gc & pc), len(pc - gc), len(gc - pc)

    s.review_correct = int(result.review_required == gt["review_required"])
    gt_values = {str(f["value"]) for f in gt["supported_facts"]}
    s.claims = len(result.claims)
    s.unsupported_claims = sum(1 for c in result.claims if not any(_appears(v, c.text) for v in gt_values))
    s.prohibited_claims = sum(1 for c in result.claims if PROHIBITED_RE.search(c.text)) + sum(
        1 for c in result.claims if any(p.lower() in c.text.lower() for p in gt["prohibited_claims"]))
    return s


def evaluate(split: str, planner=None, extractor=None, drafter=None) -> dict[str, Score]:
    planner, extractor, drafter = planner or ReadAllPlanner(), extractor or RuleExtractor(), drafter or TemplateDrafter()
    by_scenario: dict[str, Score] = defaultdict(Score)
    for case in load_cases(split):
        try:
            result = analyze(to_case_input(case), planner, extractor, drafter)
            by_scenario[case["scenario"]].add(score_case(case, result))
        except Exception as exc:  # noqa: BLE001 — a crash is a measured worker error, not a silent skip
            by_scenario[case["scenario"]].add(Score(cases=1, errors=[f"{case['case_id']}: {exc!r}"]))
    return dict(by_scenario)


def report(scores: dict[str, Score]) -> str:
    total = Score()
    for s in scores.values():
        total.add(s)
    rows = [("scenario", "cases", "fact P", "fact R", "provenance", "missing R", "missing P",
             "conflict R", "conflict P", "review acc", "unsupported", "prohibited", "errors")]
    for name, s in sorted(scores.items()) + [("ALL", total)]:
        rows.append((name, str(s.cases), _ratio(s.facts_correct, s.facts_predicted),
                     _ratio(s.facts_found, s.facts_expected), _ratio(s.provenance_ok, s.facts_found),
                     _ratio(s.missing_tp, s.missing_tp + s.missing_fn), _ratio(s.missing_tp, s.missing_tp + s.missing_fp),
                     _ratio(s.conflict_tp, s.conflict_tp + s.conflict_fn),
                     _ratio(s.conflict_tp, s.conflict_tp + s.conflict_fp),
                     _ratio(s.review_correct, s.cases), _ratio(s.unsupported_claims, s.claims),
                     str(s.prohibited_claims), str(len(s.errors))))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    lines += [f"error: {e}" for e in total.errors]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="development", choices=["development", "calibration", "holdout"])
    parser.add_argument("--final", action="store_true", help="required to touch the holdout split")
    args = parser.parse_args()
    if args.split == "holdout" and not args.final:
        raise SystemExit("Holdout is locked until rules and prompts are frozen. Re-run with --final.")
    started = time.perf_counter()
    scores = evaluate(args.split)
    print(f"split={args.split} roles=baseline (ReadAllPlanner, RuleExtractor, TemplateDrafter)")
    print(report(scores))
    print(f"runtime: {time.perf_counter() - started:.2f}s")


if __name__ == "__main__":
    main()
