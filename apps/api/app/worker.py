"""Background worker: routes webhooks, runs jobs with leases, retries and visible failures.

    python -m app.worker            # run forever
    python -m app.worker --once     # drain what is due, then exit (tests, cron)

Each job runs in two kinds of transaction: a short cross-tenant one to claim/finish it
(sal_worker, jobs only), and tenant-scoped ones for the actual work (RLS applies).
"""
from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app import repositories as repo
from app import sync
from app.db import worker_engine

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
        from app.agent.runner import baseline_roles
        self.engine = engine
        self.paypal_factory = paypal_factory
        self.roles_factory = roles_factory or baseline_roles


def _sync_all(job: repo.ClaimedJob, ctx: Context) -> dict[str, Any]:
    return sync.sync_all(job.merchant_id, ctx.paypal_factory(), ctx.engine)


def _sync_one(job: repo.ClaimedJob, ctx: Context) -> dict[str, Any]:
    dispute_id = (job.payload or {}).get("provider_dispute_id")
    if not dispute_id:
        raise PermanentError("sync_dispute job without provider_dispute_id")
    return sync.sync_one(job.merchant_id, ctx.paypal_factory(), dispute_id, ctx.engine)


def _analyze(job: repo.ClaimedJob, ctx: Context) -> dict[str, Any]:
    if job.target_id is None:
        raise PermanentError("analyze_dispute job without target dispute")
    from app.agent.runner import run_analysis
    return run_analysis(job.merchant_id, job.target_id, job.id, ctx.roles_factory(), ctx.engine)


HANDLERS: dict[str, Handler] = {
    "sync_disputes": _sync_all,
    "sync_dispute": _sync_one,
    "analyze_dispute": _analyze,
}


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

    with Session(ctx.engine) as s, s.begin():
        if outcome == "ok":
            repo.complete_job(s, job.id, result)
            log.info("job %s %s succeeded", job.kind, job.id)
        else:
            state = repo.fail_job(s, job.id, error, retryable=(outcome == "retry"))
            log.warning("job %s %s failed (%s): %s", job.kind, job.id, state, error)
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    from app.paypal import PayPalDisputes
    ctx = Context(worker_engine(), PayPalDisputes)
    if args.once:
        log.info("drained %d items", drain(ctx))
        return

    stopping = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    log.info("worker started")
    while not stopping.is_set():
        if not drain(ctx, max_items=50):
            stopping.wait(IDLE_SLEEP_SECONDS)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
