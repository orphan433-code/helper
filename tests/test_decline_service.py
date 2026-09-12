"""Свитч хоста отмены: HZ / EZE."""

from __future__ import annotations

import unittest

from core.decline_hosts import (
    decline_api_base_url,
    hz_api_base_url,
    normalize_decline_service,
)


class NormalizeServiceTests(unittest.TestCase):
    def test_default_hz(self) -> None:
        self.assertEqual(normalize_decline_service(None), "hz")
        self.assertEqual(normalize_decline_service(""), "hz")
        self.assertEqual(normalize_decline_service("HZ"), "hz")

    def test_eze_aliases(self) -> None:
        self.assertEqual(normalize_decline_service("eze"), "eze")
        self.assertEqual(normalize_decline_service("EZE"), "eze")
        self.assertEqual(normalize_decline_service("easysend"), "eze")
        self.assertEqual(normalize_decline_service("e.hz"), "eze")
        self.assertEqual(normalize_decline_service("ehz"), "eze")


class DeclineApiBaseUrlTests(unittest.TestCase):
    def test_eze_ignores_hz_monitor(self) -> None:
        cfg = {
            "dashboard": {
                "monitor_url": "https://hz.temkitemki.work/pay-out?status=new"
            },
            "bank_decline": {"api_base_url": "https://hz.temkitemki.work"},
        }
        self.assertEqual(
            decline_api_base_url(cfg, service="eze"),
            "https://e.hz.temkitemki.work",
        )

    def test_redirect_stays_hz(self) -> None:
        cfg = {
            "dashboard": {
                "monitor_url": "https://hz.temkitemki.work/pay-out?status=new"
            }
        }
        self.assertEqual(
            decline_api_base_url(cfg, service="eze", redirect=True),
            "https://hz.temkitemki.work",
        )

    def test_hz_keeps_explicit_url(self) -> None:
        cfg = {"bank_decline": {"api_base_url": "https://custom.hz.example"}}
        self.assertEqual(hz_api_base_url(cfg), "https://custom.hz.example")
        self.assertEqual(
            decline_api_base_url(cfg, service="hz"),
            "https://custom.hz.example",
        )


if __name__ == "__main__":
    unittest.main()
