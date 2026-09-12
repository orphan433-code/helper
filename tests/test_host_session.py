"""Отдельные профили HZ / e.hz (Easy)."""

from __future__ import annotations

import unittest

from core.decline_hosts import DECLINE_SERVICE_URLS
from core.host_session import (
    jwt_host_marker,
    jwt_host_needles,
    pay_out_url,
    profile_dir,
    service_from_url,
    token_cache_path,
)
from core.paths import RUNTIME_DIR


class HostSessionTests(unittest.TestCase):
    def test_url_to_service(self) -> None:
        self.assertEqual(service_from_url(DECLINE_SERVICE_URLS["eze"]), "eze")
        self.assertEqual(service_from_url("https://e.hz.temkitemki.work/pay-out"), "eze")
        self.assertEqual(service_from_url("https://hz.temkitemki.work"), "hz")
        self.assertEqual(
            service_from_url("https://hz.temkitemki.work/pay-out?status=new"),
            "hz",
        )

    def test_token_cache_split(self) -> None:
        self.assertEqual(token_cache_path("hz"), RUNTIME_DIR / "platcore_token.txt")
        self.assertEqual(token_cache_path("eze"), RUNTIME_DIR / "eze_token.txt")

    def test_eze_profile_sibling(self) -> None:
        cfg = {"browser": {"user_data_dir": "../CNY/browser_profile"}}
        hz = profile_dir(cfg, service="hz")
        eze = profile_dir(cfg, service="eze")
        self.assertEqual(hz.name, "browser_profile")
        self.assertEqual(eze.name, "browser_profile_eze")
        self.assertEqual(eze.parent, hz.parent)
        self.assertTrue(eze.is_absolute())

    def test_explicit_eze_dir(self) -> None:
        cfg = {
            "browser": {
                "user_data_dir": "../CNY/browser_profile",
                "user_data_dir_eze": "runtime/eze_profile_test",
            }
        }
        eze = profile_dir(cfg, service="eze")
        self.assertEqual(eze.name, "eze_profile_test")
        self.assertTrue(eze.is_absolute())

    def test_pay_out_and_marker(self) -> None:
        self.assertIn("e.hz.temkitemki", pay_out_url("eze"))
        self.assertNotIn("easysendglobal", pay_out_url("eze"))
        self.assertIn("hz.temkitemki.work", pay_out_url("hz"))
        self.assertNotIn("e.hz.", pay_out_url("hz"))
        self.assertEqual(jwt_host_marker("eze"), "e.hz.temkitemki")
        self.assertEqual(jwt_host_marker("hz"), "://hz.temkitemki")
        self.assertIn("e.hz.temkitemki", jwt_host_needles("eze"))
        self.assertEqual(jwt_host_needles("hz"), ("://hz.temkitemki",))

    def test_status_does_not_copy_tokens(self) -> None:
        from unittest.mock import patch

        from core import host_session as hs

        hs.invalidate_session_status()
        with (
            patch.object(hs, "read_cached_token", side_effect=lambda s: "tok" if s == "hz" else None),
            patch.object(hs, "_host_ok", side_effect=lambda s, t: s == "eze" and t == "tok"),
            patch.object(hs, "write_cached_token") as write,
        ):
            payload = hs._compute_session_status()
        self.assertFalse(payload["login_hz_ok"])
        self.assertFalse(payload["login_eze_ok"])
        write.assert_not_called()

    def test_snapshot_uses_files_when_no_probe(self) -> None:
        from unittest.mock import patch

        from core import host_session as hs

        hs.invalidate_session_status()
        with patch.object(
            hs,
            "read_cached_token",
            side_effect=lambda s: "x" if s == "eze" else None,
        ):
            snap = hs.session_status_snapshot()
        self.assertFalse(snap["login_hz_ok"])
        self.assertTrue(snap["login_eze_ok"])
        self.assertTrue(hs.session_status_stale())


class ResolveTokenCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_eze_skips_env_uses_cache(self) -> None:
        import os
        from unittest.mock import patch

        from platcore.api_client import resolve_token

        with (
            patch.dict(os.environ, {"PLATCORE_TOKEN": "hz-env"}),
            patch(
                "platcore.api_client._token_from_cache",
                side_effect=lambda s="hz": "eze-cache" if s == "eze" else None,
            ),
            patch(
                "platcore.api_client.token_works",
                side_effect=lambda url, tok: tok == "eze-cache",
            ),
            patch("platcore.api_client._save_token"),
            patch(
                "platcore.api_client._token_from_headless",
                return_value=None,
            ),
            patch(
                "platcore.api_client._tokens_from_profile_disk",
                return_value=[],
            ),
        ):
            tok = await resolve_token({}, "https://e.hz.temkitemki.work")
        self.assertEqual(tok, "eze-cache")


if __name__ == "__main__":
    unittest.main()
