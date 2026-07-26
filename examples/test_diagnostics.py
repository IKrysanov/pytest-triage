"""Failures that carry diagnostic output on stdout, stderr and the logger.

These exist so the triage report shows populated ``stdout_tail`` /
``stderr_tail`` / ``log_tail``, and to demonstrate how that captured output
sharpens the verdict: the bare assertion is ambiguous, but the logs name the
real cause. Compare the verdicts in the two sample reports for these nodeids.
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger("shop")


def test_checkout_total() -> None:
    # stdout shows the arithmetic; the model can see the expectation is stale
    # (shipping was added to the total later) rather than a code regression.
    subtotal, tax, shipping = 100.0, 8.5, 5.0
    total = subtotal + tax + shipping
    print(f"cart: subtotal={subtotal} tax={tax} shipping={shipping} total={total}")
    assert total == 108.5


def test_payment_capture() -> None:
    # The logger records the upstream response; the assertion alone only sees a
    # bool. log_tail turns an opaque "assert ok" into a clear env/infra verdict.
    status = 503
    log.error("payment upstream returned HTTP %s (gateway timeout)", status)
    log.warning("retry budget exhausted after 3 attempts to pay.svc.internal")
    ok = status == 200
    assert ok


def test_inventory_reconcile() -> None:
    # A warning on stderr flags a stale cache; the failure itself is just a count
    # mismatch. stderr explains why the numbers drifted.
    print("WARN inventory cache is 47 minutes stale", file=sys.stderr)
    counted, expected = 998, 1000
    print(f"reconcile: counted={counted} expected={expected}")
    assert counted == expected


def test_feature_flag_rollout() -> None:
    # Mixed streams: a logged config read plus a stdout state dump. Together they
    # point at a missing configuration (env), not a bug in the pricing code.
    log.warning("feature flag 'new_pricing' resolved to None (config not loaded)")
    print("pricing engine fell back to legacy path")
    price = None
    assert price is not None
