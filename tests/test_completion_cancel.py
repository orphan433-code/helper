"""Отмена сделки: регистр order_id не должен ломать поиск."""

from completion.session import (
    CompletionSession,
    DealCompletionState,
    SessionDeal,
    find_session_deal,
)
from ui.prompts import _normalize_confirm_kind


def _session_with(deal_id: str) -> CompletionSession:
    return CompletionSession(
        deals=[
            SessionDeal(
                index=1,
                order_id=deal_id,
                account_digits="5598882002190161",
                holder_name="TEST",
                amount_tjs="104.28 TJS",
                amount_target="9.54 EUR",
                state=DealCompletionState.AWAITING_PROOF,
            )
        ],
        watch_started_at=0.0,
    )


def test_find_session_deal_case_insensitive():
    session = _session_with("A64382617800")
    assert find_session_deal(session, "a64382617800") is session.deals[0]
    assert find_session_deal(session, "A64382617800") is session.deals[0]


def test_normalize_confirm_kind_preserves_order_id_case():
    assert _normalize_confirm_kind("cancel:A64382617800") == "cancel:A64382617800"
    assert _normalize_confirm_kind("RECEIPTS") == "receipts"
    assert (
        _normalize_confirm_kind("retry:rescan:A64382617800")
        == "retry:rescan:A64382617800"
    )
