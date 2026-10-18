"""Alif: отдельный банк цикла и очередь без чека."""

from __future__ import annotations

import unittest

from completion.alif_wait import (
    clear_waiting,
    drop_waiting,
    get_waiting,
    list_waiting,
    park_waiting,
    split_proof_files,
)
from core.deals_ui_local import overlay_alif_cfg
from core.payout_bank import is_alif, reset_payout_bank, set_payout_bank


class PayoutBankTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_payout_bank("activ")

    def test_default_is_activ(self) -> None:
        self.assertFalse(is_alif())

    def test_alif_token_resets(self) -> None:
        token = set_payout_bank("alif")
        self.assertTrue(is_alif())
        reset_payout_bank(token)
        self.assertFalse(is_alif())


class AlifCfgTests(unittest.TestCase):
    def test_overlay_does_not_mutate_source(self) -> None:
        src = {
            "pipeline": {"max_deals_per_run": 3},
            "validation": {"allow_visa": False, "min_amount": 10},
            "api_flow": {},
        }
        out = overlay_alif_cfg(src)
        self.assertEqual(src["pipeline"]["max_deals_per_run"], 3)
        self.assertIsInstance(out["pipeline"]["max_deals_per_run"], int)
        self.assertNotEqual(id(out), id(src))


class AlifWaitingTests(unittest.TestCase):
    def tearDown(self) -> None:
        drop_waiting("TEST-ALIF-1")

    def test_park_and_drop(self) -> None:
        park_waiting(
            {
                "order_id": "TEST-ALIF-1",
                "task_id": "uuid",
                "card": "*1111",
                "holder_name": "TEST",
                "amount_tjs": "1.00",
            }
        )
        row = get_waiting("TEST-ALIF-1")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["card"], "*1111")
        self.assertIsNotNone(row.get("parked_at"))
        self.assertIsNotNone(drop_waiting("TEST-ALIF-1"))
        self.assertIsNone(get_waiting("TEST-ALIF-1"))

    def test_clear_waiting_drops_rows(self) -> None:
        park_waiting({"order_id": "TEST-ALIF-1", "card": "*1111"})
        self.assertTrue(list_waiting())
        clear_waiting()
        self.assertEqual(list_waiting(), [])

    def test_split_shot_and_video_by_ext(self) -> None:
        self.assertEqual(split_proof_files([("чек.HEIC", "")]), (0, -1))
        self.assertEqual(
            split_proof_files([("rec.MOV", ""), ("shot.jpg", "")]),
            (1, 0),
        )
        self.assertEqual(
            split_proof_files([("clip.3gp", ""), ("a.png", "")]),
            (1, 0),
        )
        self.assertIsInstance(split_proof_files([("a.pdf", "")]), str)
        self.assertIsInstance(split_proof_files([("a.png", ""), ("b.png", "")]), str)
        self.assertIsInstance(split_proof_files([("a.mp4", "")]), str)
