"""Чек Alif: якорь «Счёт зачисления», маска 4154***VSA**1636. Activ не трогаем."""

from __future__ import annotations

import unittest

from bank.alif_flow import (
    _confirm_has_somoni,
    _find_alif_home,
    _find_card_tile,
    _find_phrase,
    _verify_confirm,
    existing_recipient_names,
    find_visa_pay_account,
    split_alif_name,
)
from completion.proof import _sync_from_phone
from core.deal_bridge import holder_for_bank
from bank.receipt import (
    _find_recipient_card_in_hits,
    cards_match,
    extract_card_parts,
    is_success_receipt,
)
from core.payout_bank import set_payout_bank
from device.ocr import OcrHit


def _hit(text: str, x: float, y: float) -> OcrHit:
    return OcrHit(text=text, confidence=1.0, x=x, y=y, width=40, height=16)


_ALIF_HITS = [
    _hit("Счёт зачисления", 129, 264),
    _hit("4154***VSA**1636", 393, 264),
    _hit("Способ оплаты", 123, 618),
    _hit("Карта 444***VSA**1634", 367, 618),
    _hit("ИСПОЛНЕНО", 266, 848),
]

_ACTIV_HITS = [
    _hit("Карта получателя", 80, 200),
    _hit("41541234****1636", 320, 200),
    _hit("Операция завершена успешно", 200, 40),
    _hit("Детали перевода", 200, 10),
]


class ActivReceiptTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_payout_bank("activ")

    def test_activ_mask_unchanged(self) -> None:
        self.assertEqual(extract_card_parts("41541234****1636"), ("41541234", "1636"))
        self.assertIsNone(extract_card_parts("4154***VSA**1636"))

    def test_activ_row_still_recipient_card(self) -> None:
        raw = "\n".join(hit.text for hit in _ACTIV_HITS)
        self.assertEqual(
            _find_recipient_card_in_hits(_ACTIV_HITS, raw),
            "41541234****1636",
        )
        self.assertTrue(is_success_receipt(_ACTIV_HITS, raw))
        set_payout_bank("activ")
        self.assertEqual(holder_for_bank("ANNA LEE"), "NA LEE")

    def test_activ_scan_still_pulls_phone(self) -> None:
        import device.phone_media as phone_media

        calls: list[str] = []
        original = phone_media.pull_new_phone_media
        phone_media.pull_new_phone_media = lambda **_kwargs: calls.append("pull")  # type: ignore[method-assign]
        try:
            _sync_from_phone(kind="screens", since_ts=0)
            self.assertEqual(calls, ["pull"])
        finally:
            phone_media.pull_new_phone_media = original


class AlifReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        set_payout_bank("alif")

    def tearDown(self) -> None:
        set_payout_bank("activ")

    def test_home_button_only_after_confirm_gone(self) -> None:
        region = (0, 0, 400, 800)
        confirm = [
            _hit("Подтвердите перевод", 200, 80),
            _hit("На главную", 200, 700),
        ]
        self.assertIsNone(_find_alif_home(confirm, region))
        success = [
            _hit("Платёж отправлен", 200, 120),
            _hit("Главный", 80, 760),
            _hit("На главную", 200, 640),
        ]
        hit = _find_alif_home(success, region)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertIn("главную", hit.text.casefold())

    def test_alif_mask_last4(self) -> None:
        self.assertEqual(extract_card_parts("4154***VSA**1636"), ("4154", "1636"))
        self.assertEqual(extract_card_parts("41541234****1636"), ("41541234", "1636"))
        self.assertEqual(extract_card_parts("MCR**8307"), ("", "8307"))
        self.assertEqual(extract_card_parts("VSA**1488"), ("", "1488"))
        self.assertEqual(extract_card_parts("QQ**5544"), ("", "5544"))
        self.assertIsNone(extract_card_parts("434914595"))
        self.assertIsNone(extract_card_parts("5 918,07 с."))

    def test_brand_mask_is_credit_account_not_payer(self) -> None:
        hits = [
            _hit("Счёт зачисления", 80, 200),
            _hit("MCR**8307", 320, 200),
            _hit("Способ оплаты", 80, 400),
            _hit("Карта VSA**1488", 320, 400),
            _hit("ИСПОЛНЕНО", 200, 520),
        ]
        raw = "\n".join(hit.text for hit in hits)
        self.assertEqual(_find_recipient_card_in_hits(hits, raw), "****8307")
        self.assertTrue(is_success_receipt(hits, raw))
        self.assertTrue(cards_match("5169490012348307", "****8307"))
        self.assertFalse(cards_match("4169490012341488", "****8307"))
        split = [
            _hit("Счёт зачисления", 80, 200),
            _hit("QQ**", 280, 200),
            _hit("5544", 360, 208),
            _hit("Номер транзакции", 80, 120),
            _hit("434914595", 320, 120),
            _hit("Сумма", 80, 280),
            _hit("5 918,07 с.", 320, 280),
            _hit("Способ оплаты", 80, 360),
            _hit("VSA**1488", 320, 360),
        ]
        raw_split = "\n".join(hit.text for hit in split)
        self.assertEqual(_find_recipient_card_in_hits(split, raw_split), "****5544")
        self.assertTrue(cards_match("5169490012345544", "****5544"))

    def test_anchor_is_credit_account_not_payment_card(self) -> None:
        raw = "\n".join(hit.text for hit in _ALIF_HITS)
        self.assertEqual(_find_recipient_card_in_hits(_ALIF_HITS, raw), "4154****1636")
        self.assertTrue(is_success_receipt(_ALIF_HITS, raw))

    def test_cards_match_recipient_not_payer(self) -> None:
        receipt = "4154****1636"
        self.assertTrue(cards_match("4154123412341636", receipt))
        self.assertFalse(cards_match("4444123412341634", receipt))
        self.assertFalse(cards_match("4154123412341634", receipt))

    def test_alif_scan_pulls_phone_like_activ(self) -> None:
        import device.phone_media as phone_media

        calls: list[str] = []
        original = phone_media.pull_new_phone_media
        phone_media.pull_new_phone_media = lambda **_kwargs: calls.append("pull")  # type: ignore[method-assign]
        try:
            _sync_from_phone(kind="screens", since_ts=0)
            _sync_from_phone(kind="videos", since_ts=0)
            self.assertEqual(calls, ["pull", "pull"])
        finally:
            phone_media.pull_new_phone_media = original

    def test_visa_account_is_any_visa_after_mobi_bonus(self) -> None:
        gold = [
            _hit("Моби", 40, 400),
            _hit("Бонус", 140, 400),
            _hit("Visa Gold", 260, 390),
            _hit("60 514,41 с.", 260, 430),
            _hit("ALF", 400, 400),
        ]
        found = find_visa_pay_account(gold)
        self.assertIsNotNone(found)
        self.assertEqual(found.text, "Visa Gold")

        platinum = [
            _hit("Моби", 40, 400),
            _hit("Бонус", 140, 400),
            _hit("Visa Platinum", 280, 410),
        ]
        found = find_visa_pay_account(platinum)
        self.assertIsNotNone(found)
        self.assertEqual(found.text, "Visa Platinum")

        split = [
            _hit("Моби", 40, 400),
            _hit("Бонус", 140, 400),
            _hit("Visa", 240, 400),
            _hit("Classic", 300, 400),
        ]
        found = find_visa_pay_account(split)
        self.assertIsNotNone(found)
        self.assertEqual(found.text, "Visa")

        stray = [
            _hit("visa help", 20, 40),
            _hit("Бонус", 140, 400),
            _hit("Виза Infinite", 260, 400),
        ]
        found = find_visa_pay_account(stray)
        self.assertIsNotNone(found)
        self.assertEqual(found.text, "Виза Infinite")

    def test_existing_recipient_names_left_alone(self) -> None:
        filled = [
            _hit("Укажите Ф. И. О. получателя на латинице", 40, 90),
            _hit("Имя", 40, 180),
            _hit("ArINTHIPEEKaya", 40, 230),
            _hit("Фамилия", 40, 310),
            _hit("InthiARAYApeek", 40, 360),
            _hit("Продолжить", 200, 700),
        ]
        self.assertEqual(
            existing_recipient_names(filled),
            ("ArINTHIPEEKaya", "InthiARAYApeek"),
        )
        empty = [
            _hit("Укажите Ф. И. О. получателя на латинице, как в его паспорте", 40, 90),
            _hit("Имя", 40, 180),
            _hit("Фамилия", 40, 280),
            _hit("Продолжить", 200, 700),
        ]
        self.assertEqual(existing_recipient_names(empty), ("", ""))
        only_last = [
            _hit("Имя", 40, 180),
            _hit("Фамилия", 40, 300),
            _hit("LEE", 40, 350),
            _hit("Продолжить", 200, 700),
        ]
        self.assertEqual(existing_recipient_names(only_last), ("", "LEE"))

    def test_name_split_and_no_trim(self) -> None:
        self.assertEqual(
            split_alif_name("ALEXANDER VASILOVSKIY"),
            ("ALEXANDER", "VASILOVSKIY"),
        )
        self.assertEqual(split_alif_name("ANNA"), ("ANNA", "ANNA"))
        self.assertEqual(holder_for_bank("ANNA LEE"), "ANNA LEE")
        tile = [
            _hit("На", 80, 420),
            _hit("карту", 82, 444),
        ]
        found = _find_phrase(tile, "На карту")
        self.assertIsNotNone(found)
        self.assertAlmostEqual(found.y, 432)
        self.assertIsNotNone(_find_phrase([_hit("Накарту", 80, 420)], "На карту"))
        self.assertIsNone(_find_phrase([_hit("Платежи", 200, 900)], "На карту"))
        # Скрин главной: «На» не читается, «карту» отдельно. «Все карты» и «Alif» мимо.
        home = [
            _hit("Оплатить", 40, 390),
            _hit("Услуги", 340, 780),
            _hit("Alif", 70, 804),
            _hit("Алифа", 340, 804),
            _hit("карту", 200, 806),
            _hit("Все карты", 80, 900),
        ]
        tile = _find_card_tile(home)
        self.assertIsNotNone(tile)
        self.assertEqual(tile.text, "карту")
        self.assertAlmostEqual(tile.x, 200)
        self.assertIsNone(
            _find_card_tile([_hit("Все карты", 80, 900), _hit("Alif", 70, 804)])
        )

    def test_confirm_somoni_is_alif_not_fee(self) -> None:
        screen = [
            _hit("836 с.", 80, 200),
            _hit("90,28 $", 80, 520),
            _hit("1% = 8,36 с.", 80, 600),
            _hit("Итого к оплате", 80, 680),
            _hit("844,36 с.", 200, 680),
        ]
        self.assertFalse(_confirm_has_somoni(screen, 828.59, 0.01))
        self.assertTrue(_confirm_has_somoni(screen, 836, 0.01))
        alif = [
            _hit("828,59 с.", 80, 200),
            _hit("89,48 $", 80, 520),
            _hit("Итого к оплате 844,36 с.", 80, 680),
        ]
        self.assertTrue(_confirm_has_somoni(alif, 828.59, 0.01))
        self.assertFalse(_confirm_has_somoni(alif, 836, 0.01))
        big = [
            _hit("7 811,09", 80, 200),
            _hit("c.", 200, 228),
            _hit("843,53 $", 80, 520),
        ]
        self.assertTrue(_confirm_has_somoni(big, 7811.09, 0.01))
        dotted = [_hit("7.811,09 с.", 80, 200)]
        self.assertTrue(_confirm_has_somoni(dotted, 7811.09, 0.01))
        glued = [_hit("781109 с.", 80, 200)]
        self.assertTrue(_confirm_has_somoni(glued, 7811.09, 0.01))

    def test_new_ledger_uses_alif_row(self) -> None:
        from platcore.api_accept import _deal_from_ledger

        row = {
            "_id": "1",
            "orderId": "A1",
            "credentials": {
                "accountNumber": "5333172196989093",
                "ownerName": "ALEXANDER SOKOLOV",
            },
            "out": {"client": 80},
            "currencyTo": {"code": "EUR"},
            "bank": {"name": "card"},
        }
        buy = {"credentials": row["credentials"], "out": {"client": 80}}
        activ = {
            "tjs": "836.00",
            "give_amt": "80.00",
            "give_cur": "eur",
            "bank": "activ",
        }
        with self.assertRaises(Exception) as caught:
            _deal_from_ledger(row=row, buy=buy, ledger=activ)
        self.assertIn("Alif", str(caught.exception))
        alif = {
            "tjs": "828.59",
            "give_amt": "89.48",
            "give_cur": "usd",
            "bank": "alif",
        }
        deal, tjs_raw, give_raw, give_cur = _deal_from_ledger(
            row=row, buy=buy, ledger=alif
        )
        self.assertEqual(tjs_raw, "828.59")
        self.assertEqual(give_raw, "89.48")
        self.assertEqual(give_cur, "USD")
        self.assertAlmostEqual(deal.amount_tjs, 828.59)
        self.assertAlmostEqual(deal.amount_usd, 89.48)
        self.assertEqual(deal.amount_eur, 0.0)
        set_payout_bank("activ")
        activ_deal, _, _, activ_cur = _deal_from_ledger(
            row=row, buy=buy, ledger=activ
        )
        self.assertEqual(activ_cur, "EUR")
        self.assertAlmostEqual(activ_deal.amount_tjs, 836.0)
        self.assertAlmostEqual(activ_deal.amount_eur, 80.0)
        stuck = {
            "tjs": "735.06",
            "give_amt": "79.38",
            "give_cur": "usd",
            "bank": "alif",
        }
        with self.assertRaises(Exception) as stuck_exc:
            _deal_from_ledger(row=row, buy=buy, ledger=stuck)
        self.assertIn("Activ", str(stuck_exc.exception))

    def test_confirm_png_uses_alif_usd_row(self) -> None:
        from completion.hz_card import card_brand_label, render_from_ledger

        alif = {
            "bank": "alif",
            "give_amt": "89.48",
            "give_cur": "usd",
            "tjs": "828.59",
            "alif_cur": "usd",
            "amount_usd": "89.48",
        }
        self.assertEqual(card_brand_label(alif, card_digits="5333172196989093"), "Alif USD")
        img = render_from_ledger(alif, card_digits="5333172196989093")
        self.assertEqual(img.size[1], 277)
        activ = {
            "bank": "activ",
            "give_amt": "80.00",
            "give_cur": "eur",
            "tjs": "836.00",
            "amount_usd": "89.48",
        }
        self.assertEqual(
            card_brand_label(activ, card_digits="5333172196989093"),
            "Activ to MC",
        )
        activ_img = render_from_ledger(activ, card_digits="5333172196989093")
        self.assertEqual(activ_img.size[1], 376)


class AlifDigitBurstTests(unittest.TestCase):
    def test_one_shell_keeps_gap_between_keys(self) -> None:
        from device.adb import digits_keyevent_script

        script = digits_keyevent_script("12,5", gap_sec=0.02)
        self.assertEqual(
            script,
            "input keyevent KEYCODE_1; sleep 0.020; "
            "input keyevent KEYCODE_2; sleep 0.020; "
            "input keyevent KEYCODE_COMMA; sleep 0.020; "
            "input keyevent KEYCODE_5",
        )
        self.assertEqual(script.count("input keyevent"), 4)

    def test_rejects_letters(self) -> None:
        from device.adb import digits_keyevent_script

        with self.assertRaises(RuntimeError):
            digits_keyevent_script("12a")


class AlifConfirmChecksTests(unittest.TestCase):
    def test_pay_screen_ignores_name(self) -> None:
        from device.ocr import OcrHit

        from bank.form import TransferFormData

        def hit(text: str, y: float) -> OcrHit:
            return OcrHit(text=text, confidence=0.9, x=10, y=y, width=40, height=12)

        screen = [
            hit("Подтвердите перевод", 40),
            hit("Tatiana Beliaevq", 120),
            hit("4111111111111111", 180),
            hit("1 062,05 $", 320),
            hit("Оплатить", 520),
        ]
        data = TransferFormData(
            account="4111111111111111",
            holder_name="TATIANA BELIAEVA",
            amount_tjs=9834.59,
            amount_usd=1062.05,
        )
        _verify_confirm(screen, data)
