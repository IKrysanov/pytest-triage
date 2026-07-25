"""Failures where the API/code is correct and the test's expectation is wrong."""

from __future__ import annotations

import requests
import shop

BASE = "https://jsonplaceholder.typicode.com"


def test_user_name() -> None:
    assert shop.fetch_user(1)["name"] == "Leanne Grahamm"


def test_user_email() -> None:
    assert shop.fetch_user(1)["email"] == "leanne@wrong.example"


def test_float_sum() -> None:
    assert 0.1 + 0.2 == 0.3


def test_user_id_type() -> None:
    assert isinstance(shop.fetch_user(1)["id"], str)


def test_user_phone() -> None:
    assert shop.fetch_user(1)["phone"] == "555-1234"


def test_user_zipcode() -> None:
    assert shop.fetch_user(1)["address"]["zipcode"] == "00000"


def test_user_field_count() -> None:
    assert len(shop.fetch_user(1)) == 99


def test_todo_completed() -> None:
    resp = requests.get(f"{BASE}/todos/1", timeout=10)
    resp.raise_for_status()
    assert resp.json()["completed"] is True
