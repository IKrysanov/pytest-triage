"""Failures from a soft-assert collector: several checks joined into one error."""

from __future__ import annotations

import shop
from softcheck import SoftAssert


def test_profile_soft() -> None:
    sa = SoftAssert()
    user = shop.fetch_user(1)
    sa.check(user["name"] == "Leanne Grahamm", f"name was {user['name']!r}")
    sa.check(user["username"] == "Brett", f"username was {user['username']!r}")
    sa.check("@wrong" in user["email"], f"email was {user['email']!r}")
    sa.assert_all()


def test_checkout_soft() -> None:
    sa = SoftAssert()
    user = shop.fetch_user(1)
    sa.check(user["name"] == "Leanne Grahamm", f"name was {user['name']!r}")
    count = shop.post_count(1)
    sa.check(count == 10, f"post_count returned {count}, expected 10")
    price = shop.apply_discount(100, 20)
    sa.check(price == 80, f"20% off 100 was {price}, expected 80")
    sa.assert_all()


def test_pricing_soft() -> None:
    sa = SoftAssert()
    d1 = shop.apply_discount(100, 20)
    sa.check(d1 == 80, f"20% off 100 was {d1}, expected 80")
    d2 = shop.apply_discount(50, 10)
    sa.check(d2 == 45, f"10% off 50 was {d2}, expected 45")
    count = shop.post_count(2)
    sa.check(count == 10, f"user 2 post_count was {count}, expected 10")
    sa.assert_all()
