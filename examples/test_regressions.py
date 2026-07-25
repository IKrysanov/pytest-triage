"""Failures caused by a defect in the code under test (the expectation is right)."""

from __future__ import annotations

import shop


def test_discounted_price() -> None:
    assert shop.apply_discount(100, 20) == 80


def test_average_score() -> None:
    assert shop.average([]) >= 0


def test_first_cart_item() -> None:
    assert shop.first_item([]) == "milk"


def test_order_total() -> None:
    assert shop.total_cents(["1099", "N/A", "500"]) == 1599


def test_customer_full_name() -> None:
    assert shop.full_name({"firstName": "Ada", "lastName": "Lovelace"})


def test_label_shout() -> None:
    assert shop.shout(None) == "SALE"


def test_line_item_total() -> None:
    assert shop.line_total("2", 9.99) == 19.98


def test_user_post_count() -> None:
    assert shop.post_count(1) == 10


def test_tree_depth() -> None:
    assert shop.depth({"child": {"value": 1}}) == 2
