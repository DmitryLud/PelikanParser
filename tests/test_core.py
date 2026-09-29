from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook, load_workbook

from pelikan_parser.excel_io import read_eurocodes, write_results
from pelikan_parser.models import Offer, SearchResult, select_minimum_offer
from pelikan_parser.text_parsing import decimal_from_price_token, extract_prices


class PriceParsingTests(unittest.TestCase):
    def test_common_price_formats(self) -> None:
        self.assertEqual(decimal_from_price_token("12 345,67 руб."), Decimal("12345.67"))
        self.assertEqual(decimal_from_price_token("9\u00a0990 BYN"), Decimal("9990"))
        self.assertEqual(decimal_from_price_token("1,234.50 RUB"), Decimal("1234.50"))

    def test_pattern_does_not_take_eurocode_without_currency(self) -> None:
        pattern = r"(?i)(?P<price>\d{1,3}(?:[ \u00A0]\d{3})*(?:[.,]\d{1,2})?)\s*(?:₽|руб(?:\.|лей)?|RUB|BYN|Br)(?!\w)"
        text = "Еврокод: 2485AGACMUVZ Цена: 12 450,50 руб."
        self.assertEqual(extract_prices(text, pattern), [Decimal("12450.50")])

    def test_ruble_sign_at_end_is_accepted(self) -> None:
        pattern = r"(?i)(?P<price>\d{1,3}(?:[ \u00A0]\d{3})*(?:[.,]\d{1,2})?)\s*(?:₽|руб(?:\.|лей)?|RUB|BYN|Br)(?!\w)"
        self.assertEqual(extract_prices("49\u00a0300 ₽", pattern), [Decimal("49300")])


class SelectionTests(unittest.TestCase):
    def test_lowest_price_and_manufacturer_are_selected_together(self) -> None:
        result = select_minimum_offer(
            "2485AGACMUVZ",
            [
                Offer(manufacturer="FYG", price=Decimal("15000")),
                Offer(manufacturer="BENSON", price=Decimal("12750")),
            ],
        )
        self.assertEqual(result.price, Decimal("12750"))
        self.assertEqual(result.manufacturer, "BENSON")
        self.assertEqual(result.status, "В наличии")

    def test_no_price_means_not_available(self) -> None:
        result = select_minimum_offer("X", [Offer(manufacturer="FYG")])
        self.assertEqual(result.status, "Нет в наличии")
        self.assertIsNone(result.price)


class ExcelTests(unittest.TestCase):
    def test_excel_input_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Eurocodes"
            sheet.append(["Eurocode"])
            sheet.append(["00123ABC"])
            sheet.append(["00123ABC"])
            sheet.append([98765])
            workbook.save(source)

            self.assertEqual(
                read_eurocodes(source, "Eurocodes", "Eurocode", deduplicate=True),
                ["00123ABC", "98765"],
            )

            target = root / "results.xlsx"
            write_results(
                target,
                [
                    SearchResult(
                        eurocode="00123ABC",
                        price=Decimal("125.50"),
                        manufacturer="FYG",
                        status="В наличии",
                        found_positions=2,
                        priced_positions=2,
                    )
                ],
            )
            output = load_workbook(target, data_only=True)
            result_sheet = output["Результат"]
            self.assertEqual(result_sheet["A2"].value, "00123ABC")
            self.assertEqual(result_sheet["B2"].value, 125.5)
            self.assertEqual(result_sheet["C2"].value, "FYG")


if __name__ == "__main__":
    unittest.main()
