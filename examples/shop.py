"""A small 'shop' domain plus a real HTTP client, used by the example suite.

Several functions carry a seeded bug so the triage has real product defects to
find (not only wrong test expectations). See examples/README.md for the intent
of each — the code here is kept comment-free on purpose so the traceback that
reaches the model is not pre-labelled.
"""

from __future__ import annotations

import requests

BASE = "https://jsonplaceholder.typicode.com"
_TIMEOUT = 10


def apply_discount(price: float, percent: float) -> float:
    return price - price * percent


def average(values: list[float]) -> float:
    return sum(values) / len(values)


def first_item(items: list[str]) -> str:
    return items[0]


def total_cents(prices: list[str]) -> int:
    return sum(int(p) for p in prices)


def full_name(user: dict) -> str:
    return user["first"] + " " + user["last"]


def shout(text: str | None) -> str:
    return text.upper()


def line_total(qty: int, price: float) -> float:
    return qty * price


def depth(node: dict) -> int:
    return 1 + depth(node["child"])


def fetch_user(user_id: int) -> dict:
    resp = requests.get(f"{BASE}/users/{user_id}", timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def post_count(user_id: int) -> int:
    resp = requests.get(f"{BASE}/posts", params={"userId": user_id}, timeout=_TIMEOUT)
    resp.raise_for_status()
    return len(resp.json()) - 1


def healthcheck(host: str) -> int:
    resp = requests.get(f"https://{host}/health", timeout=5)
    return resp.status_code
