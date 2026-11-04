"""Typing helpers for test doubles that implement only the methods a test exercises."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from openai import OpenAI

from app.worker import PayPalClient


def paypal(make: Callable[[], object]) -> Callable[[], PayPalClient]:
    """A worker.Context PayPal factory from a fake's maker; still called once per job, as the real one is."""
    return cast(Callable[[], PayPalClient], make)


NO_PAYPAL = paypal(lambda: None)   # for jobs that never call PayPal


def openai(fake: Any) -> OpenAI:
    """A fake OpenAI client: only chat.completions is implemented."""
    return cast(OpenAI, fake)
