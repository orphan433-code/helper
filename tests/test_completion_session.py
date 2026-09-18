"""Easy: чек + генерация, без видео."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from completion.session import build_session  # noqa: E402
from core.models import TzkDeal  # noqa: E402


def _accepted(*, usdt: float, ledger: dict | None) -> SimpleNamespace:
    deal = TzkDeal(
        task_id="t1",
        account_raw="5577550163963453",
        account_digits="5577550163963453",
        holder_name="IVAN",
        amount_check=100.0,
        amount_check_currency="GEL",
        amount_tjs=900.0,
        amount_eur=80.0,
        payment_method="card",
        order_id="B1",
    )
    return SimpleNamespace(
        index=1,
        deal=deal,
        order_id="B1",
        fingerprint="t1",
        amount_usdt=usdt,
        bank_skipped=False,
        ledger=ledger,
        extra_proofs=None,
        data={
            "amount_input": {"value": 900.0, "currency": "TJS"},
            "amount_verify": {"value": 80.0, "currency": "EUR"},
        },
    )


class EzeNoVideoTests(unittest.TestCase):
    def test_hz_large_wants_video(self) -> None:
        session = build_session([_accepted(usdt=800.0, ledger=None)])
        self.assertTrue(session.deals[0].needs_video)

    def test_eze_large_no_video(self) -> None:
        session = build_session(
            [_accepted(usdt=800.0, ledger={"service": "eze"})]
        )
        self.assertFalse(session.deals[0].needs_video)

    def test_force_no_video(self) -> None:
        session = build_session(
            [_accepted(usdt=800.0, ledger=None)],
            force_no_video=True,
        )
        self.assertFalse(session.deals[0].needs_video)


if __name__ == "__main__":
    unittest.main()
