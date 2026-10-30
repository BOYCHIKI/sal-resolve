"""Agent action proposals (ADR-006): which cards SAL proposes for a case or a held payment, and how a newer
proposal replaces an older one. Pure rules first, then persistence against Postgres."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import actions
from app.actions import AnalysisState, DisputeState, DraftState

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
CONTRACTS = Path(__file__).resolve().parents[3] / "contracts" / "paypal"


def dispute(**over) -> DisputeState:
    base = dict(id=UUID("11111111-0000-4000-8000-000000000001"), origin="PAYPAL_SANDBOX",
                provider_status="WAITING_FOR_SELLER_RESPONSE", deadline_at=NOW + timedelta(days=8),
                allowed_actions=("provide_evidence", "accept_claim"), amount="45.00", currency="USD")
    return DisputeState(**{**base, **over})


def prop(pid, status, reason="", sources=()):
    return {"id": pid, "status": status, "reason": reason, "sources": list(sources)}


READY = AnalysisState(readiness="READY", snapshot_hash="a" * 64, propositions=[
    prop("payment_matches", "proven", "PayPal recorded 45.00 USD", [{"evidence_id": "E2", "line": 2}]),
    prop("shipped", "proven", "Tracking JNE001 shows the parcel moving", [{"evidence_id": "E3", "line": 1}]),
    prop("delivered", "proven", "The courier marked the parcel DELIVERED", [{"evidence_id": "E3", "line": 4}]),
    prop("delivery_date_consistent", "not_applicable"),
])
MISSING = AnalysisState(readiness="NEEDS_DOCUMENTS", snapshot_hash="b" * 64, propositions=[
    prop("payment_matches", "proven", "PayPal recorded 45.00 USD"),
    prop("shipped", "proven", "Tracking JNE001 shows the parcel moving"),
    prop("delivered", "missing", "The courier's latest status is IN_TRANSIT"),
])
DRAFT = DraftState(id=UUID("22222222-0000-4000-8000-000000000002"), revision=3, status="DRAFT")


def kinds(cards):
    return [c.kind for c in cards]


# --------------------------------------------------------------- disputes
def test_ready_case_gets_one_send_card_bound_to_the_exact_draft():
    cards = actions.propose_for_dispute(dispute(), READY, DRAFT, NOW)
    assert kinds(cards) == ["SEND_EVIDENCE"]
    send = cards[0]
    assert send.payload == {"draft_id": str(DRAFT.id), "revision": 3, "snapshot_hash": "a" * 64}
    assert send.due_at == NOW + timedelta(days=8)
    assert send.subject_key == f"dispute:{dispute().id}"
    assert {"evidence_id": "E3", "line": 4} in send.sources
    assert "payment" in send.rationale and "delivery" in send.rationale


def test_missing_proof_asks_for_the_document_that_proves_it():
    cards = actions.propose_for_dispute(dispute(), MISSING, DRAFT, NOW)
    assert kinds(cards) == ["ADD_DOCUMENT"]
    assert cards[0].payload == {"missing": ["delivered"]}
    assert "proof of delivery" in cards[0].title.lower()
    assert "IN_TRANSIT" in cards[0].rationale


def test_close_deadline_adds_a_reply_card_with_hours_left():
    cards = actions.propose_for_dispute(dispute(deadline_at=NOW + timedelta(hours=30)), MISSING, DRAFT, NOW)
    assert kinds(cards) == ["REPLY_BEFORE_DEADLINE", "ADD_DOCUMENT"]
    assert "30 hours" in cards[0].title


@pytest.mark.parametrize("over, draft, analysis", [
    (dict(provider_status="RESOLVED"), DRAFT, READY),                                   # case closed
    ({}, DraftState(DRAFT.id, 3, "SUBMITTED"), READY),                                  # already sent
    ({}, DraftState(DRAFT.id, 3, "SUBMITTING"), READY),                                 # being sent
    (dict(allowed_actions=("accept_claim",)), DRAFT, READY),                            # PayPal not taking evidence
    (dict(origin="SYNTHETIC_FIXTURE"), DRAFT, READY),                                   # practice case: nothing to send
    ({}, None, None),                                                                   # not analysed yet
])
def test_no_send_card_when_sending_is_impossible_or_done(over, draft, analysis):
    assert "SEND_EVIDENCE" not in kinds(actions.propose_for_dispute(dispute(**over), analysis, draft, NOW))


def test_needs_check_is_never_offered_as_a_send():
    check = AnalysisState(readiness="NEEDS_CHECK", snapshot_hash="c" * 64, propositions=[
        prop("delivery_date_consistent", "contradicted", "Carrier and proof dates disagree")])
    assert kinds(actions.propose_for_dispute(dispute(), check, DRAFT, NOW)) == []


def test_payload_hash_changes_with_the_payload():
    a = actions.propose_for_dispute(dispute(), READY, DRAFT, NOW)[0]
    b = actions.propose_for_dispute(dispute(), READY, DraftState(DRAFT.id, 4, "DRAFT"), NOW)[0]
    assert len(a.payload_hash) == 64 and a.payload_hash != b.payload_hash


# --------------------------------------------------------------- held funds (Transaction Search)
def recorded_holds() -> list[dict]:
    path = sorted(CONTRACTS.glob("*_s10_transaction_search_holds.json"))[-1]
    return json.loads(path.read_text(encoding="utf-8"))["response"]["body"]["transaction_details"]


def tx(tid, code, ref=None, value="-10.00", status="P"):
    return {"transaction_info": {"transaction_id": tid, "paypal_reference_id": ref, "transaction_event_code": code,
                                 "transaction_status": status, "transaction_initiation_date": "2026-10-12T11:00:04Z",
                                 "transaction_amount": {"currency_code": "USD", "value": value}}}


def test_recorded_sandbox_dispute_hold_becomes_one_card():
    cards = actions.holds_from_transactions(recorded_holds(), NOW)
    assert kinds(cards) == ["EXPLAIN_HELD_FUNDS"]
    card = cards[0]
    assert card.subject_key == "hold:2MK81285P20231246:T1110"
    assert card.payload["amount"] == "43.17" and card.payload["currency"] == "USD"
    assert "43.17 USD" in card.title and "dispute" in card.rationale.lower()


def test_released_holds_and_duplicates_make_no_extra_cards():
    rows = [tx("H1", "T1110", ref="P1"), tx("R1", "T1111", ref="P1", value="10.00", status="S"),  # held, released
            tx("H2", "T2107", ref="P2"), tx("H2", "T2107", ref="P2"),                            # listed twice
            tx("S1", "T0006", ref="X")]                                                           # an ordinary sale
    cards = actions.holds_from_transactions(rows, NOW)
    assert [c.subject_key for c in cards] == ["hold:P2:T2107"]
    assert "payment" in cards[0].rationale.lower()


# --------------------------------------------------------------- persistence
@pytest.fixture
def merchant(migrated_db) -> UUID:
    from app.seed import create_merchant
    return create_merchant(f"Act-{uuid4().hex[:6]}")


def open_cards(merchant, engine):
    from app.db import tenant_session
    with tenant_session(merchant, engine) as s:
        return s.execute(text("""SELECT kind, status, payload_hash FROM agent_actions
                                 WHERE status = 'PROPOSED' ORDER BY kind""")).all()


@pytest.mark.db
def test_reproposing_keeps_identical_cards_and_supersedes_changed_ones(merchant, app_engine, worker_engine):
    from app.seed_demo import seed_golden
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    d = dispute(id=dispute_id)
    subject = f"dispute:{dispute_id}"
    first = actions.propose_for_dispute(d, READY, DRAFT, NOW)
    actions.save(merchant, subject, dispute_id, first, worker_engine)
    actions.save(merchant, subject, dispute_id, first, worker_engine)          # same again: nothing changes
    assert [(k, h) for k, _, h in open_cards(merchant, app_engine)] == [("SEND_EVIDENCE", first[0].payload_hash)]

    newer = actions.propose_for_dispute(d, MISSING, DraftState(DRAFT.id, 4, "DRAFT"), NOW)
    actions.save(merchant, subject, dispute_id, newer, worker_engine)           # a document went missing
    assert [k for k, _, _ in open_cards(merchant, app_engine)] == ["ADD_DOCUMENT"]
    from app.db import tenant_session
    with tenant_session(merchant, app_engine) as s:
        old = s.execute(text("SELECT status FROM agent_actions WHERE kind = 'SEND_EVIDENCE'")).scalar()
    assert old == "SUPERSEDED"


@pytest.mark.db
def test_api_role_can_decide_but_never_propose(merchant, app_engine, worker_engine):
    from app.db import tenant_session
    from app.seed_demo import seed_golden
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    actions.save(merchant, f"dispute:{dispute_id}", dispute_id,
                 actions.propose_for_dispute(dispute(id=dispute_id), READY, DRAFT, NOW), worker_engine)
    with pytest.raises(DBAPIError):  # no INSERT grant
        with tenant_session(merchant, app_engine) as s:
            s.execute(text("""INSERT INTO agent_actions (merchant_id, kind, subject_key, title, rationale, payload_hash)
                              VALUES (:m, 'ADD_DOCUMENT', 'x', 't', 'r', :h)"""), {"m": merchant, "h": "0" * 64})
    with pytest.raises(DBAPIError, match="cannot set an action"):
        with tenant_session(merchant, app_engine) as s:
            s.execute(text("UPDATE agent_actions SET status = 'PROPOSED'"))
    with tenant_session(merchant, app_engine) as s:  # a decision is allowed
        s.execute(text("""UPDATE agent_actions
                          SET status = 'DISMISSED', decided_by = 'operator:test', decided_at = now()"""))


@pytest.mark.db
def test_another_merchant_never_sees_the_cards(merchant, app_engine, worker_engine):
    from app.seed import create_merchant
    from app.seed_demo import seed_golden
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    actions.save(merchant, f"dispute:{dispute_id}", dispute_id,
                 actions.propose_for_dispute(dispute(id=dispute_id), READY, DRAFT, NOW), worker_engine)
    other = create_merchant("Other")
    assert open_cards(other, app_engine) == []


@pytest.mark.db
def test_scan_keeps_one_card_per_hold_and_supersedes_it_once_released(merchant, app_engine, worker_engine):
    rows = recorded_holds()
    first = actions.scan_holds(merchant, rows, NOW, worker_engine)
    again = actions.scan_holds(merchant, rows, NOW, worker_engine)              # the next sync: same holds
    assert (first["inserted"], again["inserted"], again["kept"]) == (1, 0, 1)
    assert [k for k, _, _ in open_cards(merchant, app_engine)] == ["EXPLAIN_HELD_FUNDS"]

    released = rows + [tx("R1", "T1111", ref="2MK81285P20231246", value="43.17", status="S")]
    assert actions.scan_holds(merchant, released, NOW, worker_engine)["superseded"] == 1
    assert open_cards(merchant, app_engine) == []


@pytest.mark.db
def test_a_card_the_merchant_answered_is_not_proposed_again(merchant, app_engine, worker_engine):
    from app.db import tenant_session
    from app.seed_demo import seed_golden
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    subject = f"dispute:{dispute_id}"
    missing = actions.propose_for_dispute(dispute(id=dispute_id), MISSING, DRAFT, NOW)
    actions.save(merchant, subject, dispute_id, missing, worker_engine)
    card = actions.list_actions(merchant, engine=app_engine)[0]
    actions.dismiss(merchant, card["id"], "operator:test", app_engine)
    actions.save(merchant, subject, dispute_id, missing, worker_engine)         # same suggestion: stays answered
    assert open_cards(merchant, app_engine) == []
    newer = actions.propose_for_dispute(dispute(id=dispute_id), READY, DRAFT, NOW)
    actions.save(merchant, subject, dispute_id, newer, worker_engine)           # something new: a new card
    assert [k for k, _, _ in open_cards(merchant, app_engine)] == ["SEND_EVIDENCE"]
    with tenant_session(merchant, app_engine) as s:
        assert s.execute(text("SELECT count(*) FROM agent_actions WHERE status = 'DISMISSED'")).scalar() == 1


@pytest.mark.parametrize("reason, words", [
    ("MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "partial refund"),
    ("UNAUTHORISED", "answer it there"),
])
def test_a_dispute_sal_does_not_argue_gets_an_explanation_never_a_send(reason, words):
    cards = actions.propose_for_dispute(dispute(reason=reason), READY, DRAFT, NOW)
    assert kinds(cards) == ["EXPLAIN_DISPUTE"]
    assert words in cards[0].rationale and cards[0].payload == {"reason": reason}


# --------------------------------------------------------------- bank chargeback (channel EXTERNAL)
BANK = dict(lifecycle_stage="CHARGEBACK", channel="EXTERNAL")


def test_a_claim_paypal_decides_is_not_called_a_bank_chargeback():
    # PayPal's CHARGEBACK stage on the INTERNAL channel is an escalated claim: PayPal decides, the usual send applies.
    cards = actions.propose_for_dispute(dispute(lifecycle_stage="CHARGEBACK", channel="INTERNAL"), READY, DRAFT, NOW)
    assert [c.title for c in cards] == ["Send your evidence to PayPal"]
    assert "bank" not in cards[0].rationale

READY_WITH_POD = AnalysisState(readiness="READY", snapshot_hash="d" * 64, propositions=[
    *READY.propositions[:3],
    prop("delivery_date_consistent", "proven", "Courier and proof agree on 2026-10-19", [{"evidence_id": "E4", "line": 3}]),
])


def test_a_chargeback_ready_only_on_courier_status_asks_for_the_proof_of_delivery_first():
    cards = actions.propose_for_dispute(dispute(**BANK), READY, DRAFT, NOW)
    assert kinds(cards) == ["ADD_DOCUMENT"]
    assert cards[0].title == "Add proof of delivery for the chargeback"
    assert "bank decides" in cards[0].rationale and cards[0].payload["stage"] == "CHARGEBACK"


def test_a_chargeback_with_matching_proof_of_delivery_gets_a_send_card_that_says_the_bank_decides():
    cards = actions.propose_for_dispute(dispute(**BANK), READY_WITH_POD, DRAFT, NOW)
    assert kinds(cards) == ["SEND_EVIDENCE"]
    assert cards[0].title == "Send your chargeback evidence to PayPal"
    assert "Seller Protection does not apply" in cards[0].rationale
    assert cards[0].payload["stage"] == "CHARGEBACK"


def test_a_chargeback_missing_documents_names_the_document_and_the_stage():
    cards = actions.propose_for_dispute(dispute(**BANK), MISSING, DRAFT, NOW)
    assert [c.title for c in cards] == ["Add proof of delivery for the chargeback"]
    assert "IN_TRANSIT" in cards[0].rationale


def test_an_inquiry_keeps_the_ordinary_cards():
    assert kinds(actions.propose_for_dispute(dispute(lifecycle_stage="INQUIRY"), READY, DRAFT, NOW)) == ["SEND_EVIDENCE"]


def test_a_case_paypal_is_not_taking_documents_on_explains_instead_of_asking_for_an_upload():
    d = dispute(**BANK, provider_status="UNDER_REVIEW", allowed_actions=("accept_claim",))
    cards = actions.propose_for_dispute(d, MISSING, DRAFT, NOW)
    assert [(c.kind, c.title) for c in cards] == [("EXPLAIN_DISPUTE", "PayPal is reviewing this case")]
    assert "chargeback" in cards[0].rationale


# --------------------------------------------------------------- refund offers (not as described)
SNAD = "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"
OFFERABLE = dict(reason=SNAD, lifecycle_stage="INQUIRY", allowed_actions=("make_offer", "accept_claim"),
                 offer_types=("REFUND",))


def test_a_not_as_described_inquiry_gets_a_refund_offer_card_next_to_the_explanation():
    cards = actions.propose_for_dispute(dispute(**OFFERABLE), None, None, NOW)
    assert [c.kind for c in cards] == ["EXPLAIN_DISPUTE", "OFFER_REFUND"]
    assert cards[1].payload == {"offer_type": "REFUND", "max_amount": "45.00", "currency": "USD"}
    assert "only after you approve" in cards[1].rationale


@pytest.mark.parametrize("over", [
    dict(lifecycle_stage="CHARGEBACK"),                 # PayPal takes offers only in the inquiry stage
    dict(offer_types=("REFUND_WITH_RETURN",)),          # needs the seller's return address: left to PayPal
    dict(allowed_actions=("accept_claim",)),
    dict(origin="SYNTHETIC_FIXTURE"),
    dict(reason="ITEM_NOT_RECEIVED"),                   # "not received" is argued with evidence, not refunded
])
def test_no_refund_offer_card_when_paypal_would_not_take_it(over):
    cards = actions.propose_for_dispute(dispute(**{**OFFERABLE, **over}), None, None, NOW)
    assert "OFFER_REFUND" not in [c.kind for c in cards]