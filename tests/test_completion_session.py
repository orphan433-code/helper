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

    def test_build_remembers_alif_for_live_preview(self) -> None:
        from core.payout_bank import reset_payout_bank, set_payout_bank

        token = set_payout_bank("alif")
        try:
            session = build_session([_accepted(usdt=10.0, ledger=None)])
        finally:
            reset_payout_bank(token)
        self.assertEqual(session.payout_bank, "alif")

    def test_preview_uses_session_bank(self) -> None:
        from unittest.mock import patch

        from completion.phase import preview_receipt_readiness
        from completion.session import CompletionSession, DealCompletionState, SessionDeal
        from core.payout_bank import is_alif, reset_payout_bank, set_payout_bank

        session = CompletionSession(
            payout_bank="alif",
            deals=[
                SessionDeal(
                    index=1,
                    order_id="o1",
                    account_digits="5169490012349675",
                    state=DealCompletionState.AWAITING_PROOF,
                )
            ],
        )
        seen: list[bool] = []

        def _scan(*_args, **_kwargs):
            seen.append(is_alif())
            return []

        token = set_payout_bank("activ")
        try:
            with patch("completion.phase._scan_receipts_all_folders", _scan):
                preview_receipt_readiness(session, {})
        finally:
            reset_payout_bank(token)
        self.assertEqual(seen, [True])
        self.assertFalse(is_alif())

    def test_force_no_video(self) -> None:
        session = build_session(
            [_accepted(usdt=800.0, ledger=None)],
            force_no_video=True,
        )
        self.assertFalse(session.deals[0].needs_video)


if __name__ == "__main__":
    unittest.main()
