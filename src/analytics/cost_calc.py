"""Wheel cost estimation for key-drag (膽拖) plays.

Pure stdlib. Live-app safe — no historical data dependency.

Given k keys and N drags, a complete wheel produces C(N, 6−k) tickets.
Taiwan Lotto 6/49 unit price = NT$50/ticket (since 2014 adjustment).
"""

from __future__ import annotations

from math import comb

from src.generator.lotto_picker import (
    MAX_KEY_NUMS,
    MIN_KEY_NUMS,
    TICKET_SIZE,
)

UNIT_PRICE_TWD = 50


def wheel_ticket_count(key_count: int, drag_count: int) -> int:
    """Return ticket count for a full key-drag wheel.

    Raises ValueError on invalid configuration (matches picker boundary rules).
    """
    if not isinstance(key_count, int) or isinstance(key_count, bool):
        raise ValueError("key_count must be int")
    if not isinstance(drag_count, int) or isinstance(drag_count, bool):
        raise ValueError("drag_count must be int")
    if not (MIN_KEY_NUMS <= key_count <= MAX_KEY_NUMS):
        raise ValueError(
            f"key_count must be {MIN_KEY_NUMS}-{MAX_KEY_NUMS}"
        )
    needed = TICKET_SIZE - key_count
    if drag_count < needed:
        raise ValueError(
            f"insufficient drags: need >= {needed}, got {drag_count}"
        )
    return comb(drag_count, needed)


def wheel_cost(key_count: int, drag_count: int, unit_price: int = UNIT_PRICE_TWD) -> int:
    """Return NT$ cost for a full wheel."""
    if unit_price <= 0:
        raise ValueError("unit_price must be positive")
    return wheel_ticket_count(key_count, drag_count) * unit_price


def summary(key_count: int, drag_count: int) -> dict[str, int]:
    """Combined cost summary for UI display."""
    tickets = wheel_ticket_count(key_count, drag_count)
    return {
        "needed_per_ticket": TICKET_SIZE - key_count,
        "wheel_ticket_count": tickets,
        "wheel_cost_twd": tickets * UNIT_PRICE_TWD,
    }
