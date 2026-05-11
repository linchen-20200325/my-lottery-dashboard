"""Unit tests for the wheel cost calculator."""

import unittest

from src.analytics.cost_calc import (
    UNIT_PRICE_TWD,
    summary,
    wheel_cost,
    wheel_ticket_count,
)


class TestWheelTicketCount(unittest.TestCase):
    def test_3_keys_8_drags(self):
        # need 3 of 8 → C(8,3) = 56
        self.assertEqual(wheel_ticket_count(3, 8), 56)

    def test_1_key_10_drags(self):
        # need 5 of 10 → C(10,5) = 252
        self.assertEqual(wheel_ticket_count(1, 10), 252)

    def test_5_keys_1_drag(self):
        self.assertEqual(wheel_ticket_count(5, 1), 1)


class TestCost(unittest.TestCase):
    def test_cost_matches_unit_price(self):
        self.assertEqual(wheel_cost(3, 8), 56 * UNIT_PRICE_TWD)


class TestBoundary(unittest.TestCase):
    def test_zero_keys_rejected(self):
        with self.assertRaises(ValueError):
            wheel_ticket_count(0, 6)

    def test_six_keys_rejected(self):
        with self.assertRaises(ValueError):
            wheel_ticket_count(6, 0)

    def test_insufficient_drags(self):
        with self.assertRaises(ValueError):
            wheel_ticket_count(2, 3)

    def test_summary_shape(self):
        s = summary(3, 8)
        self.assertEqual(s["needed_per_ticket"], 3)
        self.assertEqual(s["wheel_ticket_count"], 56)
        self.assertEqual(s["wheel_cost_twd"], 56 * UNIT_PRICE_TWD)


if __name__ == "__main__":
    unittest.main()
