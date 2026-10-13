"""Typed contracts between pipeline stages. Everything an LLM produces is parsed into these and
re-validated by code; nothing an LLM says is trusted as-is (SAL v1.1 D2)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

RULE_VERSION = "SAL-SYN-INR-1"

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

    def line_text(self, n: int) -> str | None:
        return next((l.text for l in self.lines if l.line == n), None)


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

    @property
    def missing(self) -> list[str]:
        return [f.field for f in self.findings if f.kind == "missing"]

    @property
    def conflicts(self) -> list[Finding]:
        return [f for f in self.findings if f.kind == "conflict"]
