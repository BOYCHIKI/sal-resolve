"""Typed contracts between pipeline stages. Everything an LLM produces is parsed into these and
re-validated by code; nothing an LLM says is trusted as-is (SAL v1.1 D2)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

RULE_VERSION = "SAL-SYN-INR-5"  # 2: one field/two values is a conflict; ASSESS stage (ADR-005)
#                                 3: delivered to the PayPal address; ordered -> shipped -> delivered in order
#                                 4: a document saying the delivery failed outvotes a dated proof
#                                 5: not-yet wording is no delivery; delivery follows the order; the parcel is tied
#                                    to this order and named on its proof

FactStatus = Literal["supported", "conflicted", "rejected"]


@dataclass(frozen=True)
class Line:
    line: int
    text: str


@dataclass(frozen=True)
class Document:
    evidence_id: str
    type: str                 # order_invoice | payment_record | carrier_tracking | delivery_proof | support_message
    lines: tuple[Line, ...]
    origin: str = "UPLOAD"    # UPLOAD (merchant file) | PAYPAL_API (fetched from PayPal) | SEED (practice data)
                              # | SELLER_INPUT (a resi the seller typed)

    def line_text(self, n: int) -> str | None:
        return next((line.text for line in self.lines if line.line == n), None)


@dataclass(frozen=True)
class CaseInput:
    """What the pipeline may see: the dispute and the evidence text. Never ground truth."""
    case_ref: str
    reason: str
    amount: str
    currency: str
    requested_evidence: tuple[str, ...]
    documents: tuple[Document, ...]


@dataclass(frozen=True)
class SourceRef:
    evidence_id: str
    line: int


@dataclass(frozen=True)
class CandidateFact:
    """Extractor output, before validation."""
    field: str
    value: str
    source: SourceRef
    quote: str                # the exact text the extractor relied on


@dataclass
class Fact:
    field: str
    value: str
    source: SourceRef
    status: FactStatus
    reason: str | None = None


@dataclass(frozen=True)
class Finding:
    """A missing-evidence item or a conflict, always with pointers."""
    kind: Literal["missing", "conflict"]
    field: str
    source_refs: tuple[SourceRef, ...]
    description: str


@dataclass(frozen=True)
class Claim:
    text: str
    fact_fields: tuple[str, ...]  # which validated facts support it


@dataclass(frozen=True)
class ToolCallRecord:
    step: int
    tool: str
    args: dict
    ok: bool
    summary: str


PropositionStatus = Literal["proven", "missing", "contradicted", "flagged", "not_applicable"]
Readiness = Literal["READY", "NEEDS_DOCUMENTS", "NEEDS_CHECK", "WEAK"]


@dataclass(frozen=True)
class Proposition:
    """Something the evidence must show (ADR-005), with the lines that show it or the reason it doesn't."""
    id: str
    status: PropositionStatus
    reason: str
    sources: tuple[SourceRef, ...] = ()


@dataclass(frozen=True)
class Assessment:
    propositions: tuple[Proposition, ...]
    readiness: Readiness
    next_action: str

    def status(self, proposition_id: str) -> str:
        return next(p.status for p in self.propositions if p.id == proposition_id)


@dataclass
class AnalysisResult:
    rule_version: str
    facts: list[Fact]
    findings: list[Finding]
    claims: list[Claim]
    rejected_claims: list[Claim]
    review_required: bool
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    snapshot_hash: str = ""
    assessment: Assessment | None = None

    @property
    def missing(self) -> list[str]:
        return [f.field for f in self.findings if f.kind == "missing"]

    @property
    def conflicts(self) -> list[Finding]:
        return [f for f in self.findings if f.kind == "conflict"]
