"""Failures caused by the environment: unreachable hosts and real server errors."""

from __future__ import annotations

import requests
import shop


def test_payments_health() -> None:
    assert shop.healthcheck("payments.internal.invalid") == 200


def test_auth_health() -> None:
    assert shop.healthcheck("auth.corp.invalid") == 200


def test_cache_ping() -> None:
    resp = requests.get("https://cache.svc.invalid/ping", timeout=5)
    assert resp.status_code == 200


def test_orders_endpoint() -> None:
    resp = requests.get("https://httpbin.org/status/500", timeout=15)
    resp.raise_for_status()
    assert resp.json()["orders"]


def test_inventory_endpoint() -> None:
    resp = requests.get("https://httpbin.org/status/503", timeout=15)
    resp.raise_for_status()
    assert resp.status_code == 200


def test_slow_upstream() -> None:
    resp = requests.get("https://httpbin.org/delay/10", timeout=2)
    assert resp.status_code == 200
