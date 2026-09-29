from __future__ import annotations

import functools
import http.server
import tempfile
import threading
import unittest
from decimal import Decimal
from pathlib import Path

from pelikan_parser.browser import SiteParser
from pelikan_parser.config import AppConfig


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class BrowserIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = Path(__file__).parent / "fixtures" / "site"
        handler = functools.partial(QuietHandler, directory=str(fixture))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def test_login_search_minimum_and_no_stock(self) -> None:
        port = self.server.server_address[1]
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            config = AppConfig(
                path=base / "config.yaml",
                raw={
                    "site": {
                        "login_url": f"http://127.0.0.1:{port}/login.html",
                        "catalog_url": "",
                    },
                    "browser": {
                        "headless": True,
                        "timeout_ms": 5000,
                        "results_timeout_ms": 2000,
                        "after_search_delay_ms": 50,
                        "storage_state_path": str(base / "state.json"),
                    },
                    "selectors": {
                        "login": {
                            "email": ["placeholder=Адрес электронной почты"],
                            "password": ["css=input[type='password']"],
                            "submit": ["role=button|Вход"],
                        },
                        "catalog": {
                            "search_input": ["placeholder=Наименование | еврокод | OEM номер"],
                            "search_submit": ["role=button|Поиск"],
                        },
                        "results": {
                            "item": [
                                "xpath=//ul/li/article[.//span[normalize-space()='Производитель:'] and .//span[normalize-space()='Еврокод:']]"
                            ],
                            "manufacturer": [
                                "xpath=.//p[span[normalize-space()='Производитель:']]"
                            ],
                            "price": ["xpath=.//p[contains(normalize-space(.), '₽')]"],
                            "availability": [
                                "xpath=.//*[contains(normalize-space(.), 'Наличие на складе:') and not(.//*[contains(normalize-space(.), 'Наличие на складе:')])]"
                            ],
                            "empty": ["text=По вашему запросу ничего не найдено"],
                        },
                    },
                    "patterns": {
                        "manufacturer": r"(?im)Производитель\s*:\s*([^\r\n]+)",
                        "price": r"(?i)(?P<price>\d{1,3}(?:[ \u00A0]\d{3})*(?:[.,]\d{1,2})?)\s*(?:₽|руб(?:\.|лей)?|RUB|BYN|Br)(?!\w)",
                        "availability": r"(?im)Наличие(?: на складе)?\s*:\s*([^\r\n]+)",
                    },
                },
            )
            with SiteParser(config, "user@example.com", "password", headless_override=True) as parser:
                parser.login()
                available = parser.search("2485AGACMUVZ")
                missing = parser.search("NO-STOCK")
                unknown = parser.search("UNKNOWN")

            self.assertEqual(available.price, Decimal("12750.50"))
            self.assertEqual(available.manufacturer, "BENSON")
            self.assertEqual(available.status, "В наличии")
            self.assertEqual(missing.status, "Нет в наличии")
            self.assertEqual(missing.found_positions, 2)
            self.assertEqual(unknown.status, "Нет в наличии")
            self.assertEqual(unknown.found_positions, 0)


if __name__ == "__main__":
    unittest.main()
