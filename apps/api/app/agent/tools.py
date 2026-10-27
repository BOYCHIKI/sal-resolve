"""Read-only tools for the gather stage. Bound to one case; the model can only choose safe arguments.

Write tools (provide_evidence, accept_claim, make_offer, send_message) do not exist here at all:
an agent asking for one gets a rejection recorded in the audit trail, never an action.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.models import CaseInput, ToolCallRecord

WRITE_TOOLS = {"provide_evidence", "accept_claim", "make_offer", "send_message", "escalate", "refund"}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    params: dict[str, str]


TOOL_SPECS = (
    ToolSpec("get_dispute", "Reason, amount and currency of this dispute.", {}),
    ToolSpec("get_requested_evidence", "Evidence types PayPal explicitly requested from the seller.", {}),
    ToolSpec("list_evidence", "Evidence documents attached to this case (id and type).", {}),
    ToolSpec("read_evidence", "Full text of one document from list_evidence, with line numbers.",
             {"evidence_id": "an id returned by list_evidence"}),
)


class CaseToolbox:
    def __init__(self, case: CaseInput) -> None:
        self._case = case
        self._docs = {d.evidence_id: d for d in case.documents}
        self.records: list[ToolCallRecord] = []
        self.read_ids: list[str] = []

    def call(self, step: int, name: str, args: dict[str, Any]) -> dict[str, Any]:
        result, ok, summary = self._dispatch(name, args or {})
        self.records.append(ToolCallRecord(step, name, _safe_args(args), ok, summary))
        return result

    def _dispatch(self, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], bool, str]:
        if name in WRITE_TOOLS:
            return {"error": "write actions are not available to the agent"}, False, "rejected: write tool"
        if name == "get_dispute":
            c = self._case
            return {"reason": c.reason, "amount": c.amount, "currency": c.currency}, True, "dispute summary"
        if name == "get_requested_evidence":
            return {"requested": list(self._case.requested_evidence)}, True, "requested evidence"
        if name == "list_evidence":
            docs = [{"evidence_id": d.evidence_id, "type": d.type} for d in self._case.documents]
            return {"documents": docs}, True, f"{len(docs)} documents"
        if name == "read_evidence":
            doc = self._docs.get(str(args.get("evidence_id", "")))
            if doc is None:
                return {"error": "unknown evidence_id for this case"}, False, "rejected: evidence not in case"
            self.read_ids.append(doc.evidence_id)
            # Text is returned as data with an explicit label; instructions inside it carry no authority.
            return {"evidence_id": doc.evidence_id, "type": doc.type, "untrusted_document_text": True,
                    "lines": [{"line": line.line, "text": line.text} for line in doc.lines]}, True, f"read {doc.evidence_id}"
        return {"error": f"unknown tool {name!r}"}, False, "rejected: unknown tool"


def _safe_args(args: dict[str, Any] | None) -> dict[str, Any]:
    """Only short scalar arguments reach the audit log."""
    return {k: (v if isinstance(v, (int, float, bool)) else str(v)[:64]) for k, v in (args or {}).items()}
