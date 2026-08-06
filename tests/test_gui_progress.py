"""Тесты gui_progress."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from completion.session import CompletionSession, DealCompletionState, SessionDeal
from ui.progress import (
    PipelineProgressTracker,
    notify_completion_progress,
    set_completion_progress_handler,
    set_pipeline_progress_handler,
)
from core.models import RowPreview, TzkDeal


class GuiProgressTests(unittest.TestCase):
    def test_notify_builds_payload(self) -> None:
        received: list[dict] = []
        session = CompletionSession(
            deals=[
                SessionDeal(
                    index=1,
                    order_id="a",
                    account_digits="1234567890123456",
                    holder_name="IVAN",
                    amount_tjs="100 TJS",
                    state=DealCompletionState.COMPLETED,
                ),
                SessionDeal(
                    index=2,
                    order_id="b",
                    account_digits="9876543210987654",
                    state=DealCompletionState.AWAITING_PROOF,
                ),
            ]
        )

        def handler(payload: dict) -> None:
            received.append(payload)

        set_completion_progress_handler(handler)
        try:
            notify_completion_progress(
                session,
                phase="done",
                message="Все 2 чеков загружены успешно",
            )
        finally:
            set_completion_progress_handler(None)

        self.assertEqual(len(received), 1)
        payload = received[0]
        self.assertEqual(payload["phase"], "done")
        self.assertEqual(payload["done"], 1)
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["deals"][0]["state"], "done")
        self.assertEqual(payload["deals"][0]["card"], "*3456")
        self.assertEqual(payload["deals"][1]["state"], "pending")

    def test_pipeline_tracker_flow(self) -> None:
        received: list[dict] = []
        set_pipeline_progress_handler(received.append)
        try:
            tracker = PipelineProgressTracker(total=7)
            tracker.begin_search()
            preview = RowPreview(
                fingerprint="fp1",
                time_text="",
                amount_raw="500 TJS",
                account_raw="****3456",
                holder_raw="IVAN",
                payment_method="card",
                amount_usdt_raw="12.5",
            )
            tracker.start_accept(1, preview)
            deal = TzkDeal(
                task_id="t1",
                account_raw="1234567890123456",
                account_digits="1234567890123456",
                holder_name="IVAN",
                amount_check=500.0,
                amount_check_currency="TJS",
                amount_tjs=500.0,
                amount_eur=0.0,
                payment_method="card",
                order_id="ord-1",
            )
            accepted = SimpleNamespace(
                index=1,
                deal=deal,
                order_id="ord-1",
                amount_usdt=12.5,
                data={
                    "account": {"digits": "1234567890123456"},
                    "holder_name": "IVAN",
                    "amount_input": {"value": 500.0, "currency": "TJS"},
                },
            )
            tracker.mark_accepted(accepted)
            tracker.mark_paying(1)
            tracker.mark_paid(1)
            tracker.finish()
        finally:
            set_pipeline_progress_handler(None)

        self.assertGreaterEqual(len(received), 5)
        last = received[-1]
        self.assertEqual(last["phase"], "done")
        self.assertEqual(last["paid"], 1)
        self.assertEqual(last["total"], 7)
        self.assertEqual(last["remaining"], 6)
        self.assertEqual(last["deals"][0]["state"], "paid")
        self.assertEqual(last["deals"][0]["card"], "*3456")
        self.assertIn("Выплачено 1 из 7", last["message"])


if __name__ == "__main__":
    unittest.main()
