"""Score the pipeline against the golden dataset.

    python -m app.agent.evaluate                      # development split, baseline roles
    python -m app.agent.evaluate --split calibration
    python -m app.agent.evaluate --split holdout --final   # only once rules/prompts are frozen
    python -m app.agent.evaluate --split real_format --roles llm   # realistic layouts (v1.1.0, ADR-004 gate)
    python -m app.agent.evaluate --split sea_dev --roles llm       # Indonesian/Philippine formats (v1.2.0)

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
# Realistic layouts (dates in words, symbols, e-mails, scans). Not frozen like v1.0.0; regenerate with
# data/golden/make_real_format.py.
SPLIT_DIRS = {"real_format": REPO_ROOT / "data" / "golden" / "v1.1.0",
              # Indonesian and Philippine seller formats (data/golden/make_sea_format.py). sea_holdout is scored
              # only with --final, after rules and prompts are frozen.
              "sea_dev": REPO_ROOT / "data" / "golden" / "v1.2.0",
              "sea_holdout": REPO_ROOT / "data" / "golden" / "v1.2.0"}
HOLDOUT_SPLITS = {"holdout", "sea_holdout"}


def load_cases(split: str, golden_dir: Path = GOLDEN_DIR) -> list[dict[str, Any]]:
    path = golden_dir / split / "cases.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def to_case_input(case: dict[str, Any]) -> CaseInput:
    d = case["dispute"]
    # Dataset documents stand in for what PayPal and the merchant would provide (practice data: SEED).
    docs = tuple(Document(e["evidence_id"], e["type"], tuple(Line(line["line"], line["text"]) for line in e["content_lines"]),
                          "SEED") for e in case["evidence"])
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
    readiness_correct: int = 0    # ASSESS readiness vs the readiness implied by the labels (ADR-005)
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


def expected_readiness(case: dict[str, Any]) -> str:
    """Readiness implied by the labels alone, independent of extraction:
    any labelled conflict -> NEEDS_CHECK; no courier documents at all -> WEAK; anything missing (including a
    payment record) -> NEEDS_DOCUMENTS; otherwise READY."""
    gt = case["ground_truth"]
    if gt["conflicts"]:
        return "NEEDS_CHECK"
    missing = set(gt["missing_evidence"])
    if {"carrier_tracking", "delivery_proof"} <= missing:
        return "WEAK"
    if missing or not any(e["type"] == "payment_record" for e in case["evidence"]):
        return "NEEDS_DOCUMENTS"
    return "READY"


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
    s.readiness_correct = int(result.assessment is not None and result.assessment.readiness == expected_readiness(case))
    gt_values = {str(f["value"]) for f in gt["supported_facts"]}
    s.claims = len(result.claims)
    s.unsupported_claims = sum(1 for c in result.claims if not any(_appears(v, c.text) for v in gt_values))
    s.prohibited_claims = sum(1 for c in result.claims if PROHIBITED_RE.search(c.text)) + sum(
        1 for c in result.claims if any(p.lower() in c.text.lower() for p in gt["prohibited_claims"]))
    return s


def evaluate(split: str, planner=None, extractor=None, drafter=None, limit: int | None = None) -> dict[str, Score]:
    planner, extractor, drafter = planner or ReadAllPlanner(), extractor or RuleExtractor(), drafter or TemplateDrafter()
    by_scenario: dict[str, Score] = defaultdict(Score)
    cases = load_cases(split, SPLIT_DIRS.get(split, GOLDEN_DIR))
    if limit:  # one case per scenario first, so a small run still covers every scenario
        cases = sorted(cases, key=lambda c: [x['case_id'] for x in cases if x['scenario'] == c['scenario']].index(c['case_id']))[:limit]
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['case_id']} ...", end=" ", flush=True)
        t0 = time.perf_counter()
        try:
            result = analyze(to_case_input(case), planner, extractor, drafter)
            scored = score_case(case, result)
            print(f"ok {time.perf_counter() - t0:.1f}s  facts {scored.facts_found}/{scored.facts_expected}"
                  f"  rejected {sum(f.status == 'rejected' for f in result.facts)}", flush=True)
            by_scenario[case["scenario"]].add(scored)
        except Exception as exc:  # noqa: BLE001 — a crash is a measured worker error, not a silent skip
            print(f"ERROR {type(exc).__name__}", flush=True)
            by_scenario[case["scenario"]].add(Score(cases=1, errors=[f"{case['case_id']}: {exc!r}"]))
    return dict(by_scenario)


def report(scores: dict[str, Score]) -> str:
    total = Score()
    for s in scores.values():
        total.add(s)
    rows = [("scenario", "cases", "fact P", "fact R", "provenance", "missing R", "missing P",
             "conflict R", "conflict P", "review acc", "ready acc", "unsupported", "prohibited", "errors")]
    for name, s in sorted(scores.items()) + [("ALL", total)]:
        rows.append((name, str(s.cases), _ratio(s.facts_correct, s.facts_predicted),
                     _ratio(s.facts_found, s.facts_expected), _ratio(s.provenance_ok, s.facts_found),
                     _ratio(s.missing_tp, s.missing_tp + s.missing_fn), _ratio(s.missing_tp, s.missing_tp + s.missing_fp),
                     _ratio(s.conflict_tp, s.conflict_tp + s.conflict_fn),
                     _ratio(s.conflict_tp, s.conflict_tp + s.conflict_fp),
                     _ratio(s.review_correct, s.cases), _ratio(s.readiness_correct, s.cases),
                     _ratio(s.unsupported_claims, s.claims),
                     str(s.prohibited_claims), str(len(s.errors))))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)) for r in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    lines += [f"error: {e}" for e in total.errors]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="development", choices=["development", "calibration", "holdout", "real_format", "sea_dev", "sea_holdout"])
    parser.add_argument("--final", action="store_true", help="required to touch the holdout split")
    parser.add_argument("--roles", default="baseline", choices=["baseline", "llm"])
    parser.add_argument("--limit", type=int, help="score only N cases (free-tier quotas)")
    args = parser.parse_args()
    if args.split in HOLDOUT_SPLITS and not args.final:
        raise SystemExit("Holdout is locked until rules and prompts are frozen. Re-run with --final.")
    started = time.perf_counter()
    if args.roles == "llm":
        from app.agent.llm import LLMRoles
        from app.config import get_settings
        get_settings()  # loads apps/api/.env
        from app.agent.roles import LabelExtractor, RuleExtractor, UnionExtractor
        llm = LLMRoles()  # same composition as the worker (runner.configured_roles)
        scores = evaluate(args.split, extractor=UnionExtractor(RuleExtractor(), LabelExtractor(), llm), drafter=llm, limit=args.limit)
        print(f"split={args.split} roles=rules+llm model={llm.model} {llm.options}")
    else:
        scores = evaluate(args.split, limit=args.limit)
        print(f"split={args.split} roles=baseline (ReadAllPlanner, RuleExtractor, TemplateDrafter)")
    print(report(scores))
    print(f"runtime: {time.perf_counter() - started:.2f}s")


if __name__ == "__main__":
    main()
