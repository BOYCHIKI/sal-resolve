"""Background worker: routes webhooks, runs jobs with leases, retries and visible failures.

    python -m app.worker            # run forever
    python -m app.worker --once     # drain what is due, then exit (tests, cron)

Each job runs in two kinds of transaction: a short cross-tenant one to claim/finish it
(sal_worker, jobs only), and tenant-scoped ones for the actual work (RLS applies).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import signal
import threading
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app import logs
from app import repositories as repo
from app import sync
from app.db import tenant_session, worker_engine

log = logging.getLogger("sal.worker")

LEASE_SECONDS = 60
HEARTBEAT_SECONDS = 20
IDLE_SLEEP_SECONDS = 1.0


class PermanentError(Exception):
    """Retrying cannot help (bad input, unknown kind). The job fails immediately."""


Handler = Callable[[repo.ClaimedJob, "Context"], dict[str, Any]]


class Context:
    def __init__(self, engine: Engine, paypal_factory: Callable[[], sync.DisputeSource],
                 roles_factory: Callable[[], Any] | None = None) -> None:
        from app.agent.runner import configured_roles
        self.engine = engine
        self.paypal_factory = paypal_factory
        self.roles_factory = roles_factory or configured_roles


def _sync_all(job: repo.ClaimedJob, ctx: Context) -> dict[str, Any]:
    return sync.sync_all(job.merchant_id, ctx.paypal_factory(), ctx.engine)


def _sync_one(job: repo.ClaimedJob, ctx: Context) -> dict[str, Any]:
    dispute_id = (job.payload or {}).get("provider_dispute_id")
    if not dispute_id:
        raise PermanentError("sync_dispute job without provider_dispute_id")
    try:
        return sync.sync_one(job.merchant_id, ctx.paypal_factory(), dispute_id, ctx.engine)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 403, 404):  # retrying cannot fix a missing or forbidden dispute
            raise PermanentError(f"PayPal answered {exc.response.status_code} for dispute {dispute_id}") from exc
        raise


def _analyze(job: repo.ClaimedJob, ctx: Context) -> dict[str, Any]:
    if job.target_id is None:
        raise PermanentError("analyze_dispute job without target dispute")
    from app.agent.runner import run_analysis
    from app.packing import attach_to_dispute
    attach_to_dispute(job.merchant_id, job.target_id, ctx.engine)   # a matching packing record is read too
    return run_analysis(job.merchant_id, job.target_id, job.id, ctx.roles_factory(), ctx.engine)


def _reconcile(job: repo.ClaimedJob, ctx: Context) -> dict[str, Any]:
    draft_id = (job.payload or {}).get("draft_id")
    if not draft_id:
        raise PermanentError("reconcile_submission job without draft_id")
    from app.submission import reconcile
    return reconcile(job.merchant_id, UUID(draft_id), ctx.paypal_factory(), ctx.engine)


def _paypal_evidence(job: repo.ClaimedJob, ctx: Context) -> dict[str, Any]:
    if job.target_id is None:
        raise PermanentError("paypal_evidence job without target dispute")
    from app.paypal_evidence import fetch_and_store
    try:
        return fetch_and_store(job.merchant_id, job.target_id, ctx.paypal_factory(), ctx.engine)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 401, 403, 404):  # e.g. Transaction Search not enabled for the app
            raise PermanentError(f"PayPal answered {exc.response.status_code} to Transaction Search") from exc
        raise


def _propose_actions(job: repo.ClaimedJob, ctx: Context) -> dict[str, Any]:
    if job.target_id is None:
        raise PermanentError("propose_actions job without target dispute")
    from datetime import datetime, timezone

    from app.actions import refresh_dispute
    return refresh_dispute(job.merchant_id, job.target_id, datetime.now(timezone.utc), ctx.engine)


def _scan_holds(job: repo.ClaimedJob, ctx: Context) -> dict[str, Any]:
    from datetime import datetime, timezone

    from app.actions import scan_holds
    try:
        rows = ctx.paypal_factory().recent_transactions()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 401, 403):  # e.g. Transaction Search not enabled for the app
            raise PermanentError(f"PayPal answered {exc.response.status_code} to Transaction Search") from exc
        raise
    return scan_holds(job.merchant_id, rows, datetime.now(timezone.utc), ctx.engine)


def _refresh_actions(job: repo.ClaimedJob, ctx: Context) -> dict[str, Any]:
    from datetime import datetime, timezone

    from app.actions import refresh_open_disputes
    from app.config import get_settings
    from app.packing import attach_to_dispute, purge_expired
    # A packing record made after the dispute arrived is attached here, then the case is analysed again.
    with tenant_session(job.merchant_id, ctx.engine) as s:
        open_ids = s.execute(text("""SELECT id FROM disputes WHERE provider_status IS DISTINCT FROM 'RESOLVED'""")
                             ).scalars().all()
    attached = 0
    for dispute_id in open_ids:
        n = attach_to_dispute(job.merchant_id, dispute_id, ctx.engine)
        if n:
            attached += n
            with tenant_session(job.merchant_id, ctx.engine) as s:
                repo.enqueue_job(s, job.merchant_id, "analyze_dispute", f"analyze:{dispute_id}:packing:{job.id}",
                                 dispute_id)
    result = refresh_open_disputes(job.merchant_id, datetime.now(timezone.utc), ctx.engine)
    return {**result, "packing_attached": attached,
            "packing_purged": purge_expired(job.merchant_id, get_settings().storage_dir, ctx.engine)}


HANDLERS: dict[str, Handler] = {
    "sync_disputes": _sync_all,
    "sync_dispute": _sync_one,
    "analyze_dispute": _analyze,
    "reconcile_submission": _reconcile,
    "paypal_evidence": _paypal_evidence,
    "propose_actions": _propose_actions,
    "scan_holds": _scan_holds,
    "refresh_actions": _refresh_actions,
}


# ---------------------------------------------------------------- autonomous watch (ADR-006)
def watched_merchants(engine: Engine, demo_merchant_id: UUID | None) -> list[UUID]:
    """Merchants SAL watches on its own: every connected PayPal account, plus the demo merchant."""
    with Session(engine) as s, s.begin():
        ids = set(s.execute(text("SELECT DISTINCT merchant_id FROM paypal_connections")).scalars())
    if demo_merchant_id is not None:
        ids.add(demo_merchant_id)
    return sorted(ids, key=str)


def watch_tick(engine: Engine, merchants: list[UUID], now_epoch: float, minutes: int, paypal_ready: bool) -> int:
    """Queue one round of checks per merchant: sync PayPal, scan held funds, refresh every open case's cards.
    The job key names the time window, so a restart or a second worker never queues the same round twice.
    Nothing here writes to PayPal; the round only reads and proposes."""
    window = int(now_epoch // (minutes * 60))
    kinds = (["sync_disputes", "scan_holds"] if paypal_ready else []) + ["refresh_actions"]
    queued = 0
    for merchant_id in merchants:
        with tenant_session(merchant_id, engine) as s:
            for kind in kinds:
                queued += repo.enqueue_job(s, merchant_id, kind, f"watch:{kind}:{merchant_id}:{window}")
    return queued


# ---------------------------------------------------------------- webhooks
def _seller_merchant_id(event: dict[str, Any]) -> str | None:
    txns = (event.get("resource") or {}).get("disputed_transactions") or []
    return ((txns[0].get("seller") or {}).get("merchant_id")) if txns else None


def route_one_webhook(engine: Engine) -> bool:
    """Turn one verified webhook into a tenant job. Returns False when nothing was pending."""
    with Session(engine) as s, s.begin():
        event = repo.claim_webhook_event(s)
        if event is None:
            return False
        payload = event["payload"]
        if not event["event_type"].startswith("CUSTOMER.DISPUTE.") or not event["resource_id"]:
            repo.mark_webhook_processed(s, event["id"], "ignored: not a dispute event")
            return True
        seller = _seller_merchant_id(payload)
        merchant_id = repo.merchant_for_paypal_account(s, seller) if seller else None
        if merchant_id is None:
            repo.mark_webhook_processed(s, event["id"], f"unroutable: no merchant for seller {seller!r}")
            return True
        # Switch into the tenant for this transaction only, then enqueue a deduplicated sync.
        s.execute(text("SELECT set_config('app.merchant_id', :m, true)"), {"m": str(merchant_id)})
        repo.enqueue_job(s, merchant_id, "sync_dispute", f"webhook:{event['provider_event_id']}",
                         payload={"provider_dispute_id": event["resource_id"]})
        repo.mark_webhook_processed(s, event["id"])
    return True


# ---------------------------------------------------------------- jobs
def _heartbeat(engine: Engine, job_id: UUID, stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_SECONDS):
        with Session(engine) as s, s.begin():
            repo.extend_lease(s, job_id, LEASE_SECONDS)


def run_one_job(ctx: Context) -> bool:
    with Session(ctx.engine) as s, s.begin():
        repo.fail_exhausted_jobs(s)
        job = repo.claim_job(s, LEASE_SECONDS)
    if job is None:
        return False

    stop = threading.Event()
    beat = threading.Thread(target=_heartbeat, args=(ctx.engine, job.id, stop), daemon=True)
    beat.start()
    tokens = (logs.job_id.set(str(job.id)), logs.merchant_id.set(str(job.merchant_id)),
              logs.dispute_id.set(str(job.target_id) if job.target_id else None))
    started = time.perf_counter()
    try:
        handler = HANDLERS.get(job.kind)
        if handler is None:
            raise PermanentError(f"unknown job kind {job.kind!r}")
        result = handler(job, ctx)
    except PermanentError as exc:
        outcome, error = "permanent", str(exc)
    except Exception as exc:  # noqa: BLE001 — every failure must land in the job row, not vanish
        outcome, error = "retry", f"{type(exc).__name__}: {exc}"
    else:
        outcome, error = "ok", None
    finally:
        stop.set()
        beat.join(timeout=5)

    duration_ms = int((time.perf_counter() - started) * 1000)
    with Session(ctx.engine) as s, s.begin():
        if outcome == "ok":
            repo.complete_job(s, job.id, result)
            log.info("job %s succeeded", job.kind, extra={"kind": job.kind, "outcome": "ok", "duration_ms": duration_ms})
        else:
            state = repo.fail_job(s, job.id, error, retryable=(outcome == "retry"))
            log.warning("job %s failed (%s)", job.kind, state,
                        extra={"kind": job.kind, "outcome": state, "duration_ms": duration_ms, "error": error})
    for var, token in zip((logs.job_id, logs.merchant_id, logs.dispute_id), tokens, strict=True):
        var.reset(token)
    return True


def drain(ctx: Context, max_items: int = 1000) -> int:
    done = 0
    while done < max_items and (route_one_webhook(ctx.engine) or run_one_job(ctx)):
        done += 1
    return done


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logs.setup()
    from app.config import require_valid
    cfg = require_valid()
    log.info("worker config", extra={"kind": "config", "outcome": json.dumps(cfg.summary())})

    from functools import lru_cache

    from app.paypal import PayPalDisputes
    # One PayPal client per worker process: its OAuth token is reused until it expires instead of being
    # fetched again for every job. Created lazily, so a worker without PayPal credentials still runs analyses.
    ctx = Context(worker_engine(), lru_cache(maxsize=1)(PayPalDisputes))
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    if args.once:
        log.info("drained %d items", drain(ctx))
        return

    stopping = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    log.info("worker started")
    last_beat = 0.0
    last_watch = float("-inf")
    paypal_ready = bool(cfg.paypal_client_id and cfg.paypal_client_secret)
    while not stopping.is_set():
        if cfg.watch_minutes and time.monotonic() - last_watch >= cfg.watch_minutes * 60:
            try:
                queued = watch_tick(ctx.engine, watched_merchants(ctx.engine, cfg.demo_merchant_id), time.time(),
                                    cfg.watch_minutes, paypal_ready)
                log.info("watch round queued %d jobs", queued)
            except Exception:  # noqa: BLE001 — a failed round is retried next window, the worker keeps running
                log.exception("watch round failed")
            last_watch = time.monotonic()
        done = drain(ctx, max_items=50)
        if done or time.monotonic() - last_beat > HEARTBEAT_SECONDS / 2:  # liveness for /api/health
            with Session(ctx.engine) as s, s.begin():
                repo.worker_heartbeat(s, worker_id, done)
            last_beat = time.monotonic()
        if not done:
            stopping.wait(IDLE_SLEEP_SECONDS)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
