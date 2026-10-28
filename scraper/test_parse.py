"""Test simple del parser con el HTML guardado en data/raw/ (no hace requests).

Uso: python -m unittest scraper.test_parse -v
"""
import unittest

from scraper.client import RAW_DIR
from scraper.parse import (COLUMNS, clean_url, model_from_title, parse_card, parse_page, split_location,
                           title_hint, FUEL_HINTS, TRANSMISSION_HINTS, version_from_title)


class TestHelpers(unittest.TestCase):
    def test_clean_url(self):
        self.assertEqual(clean_url("https://x/volkswagen/gol/dueno/_NoIndex_True#a=1"),
                         "https://x/volkswagen/gol/dueno/")

    def test_location(self):
        self.assertEqual(split_location("Pocitos Nuevo - Montevideo"), ("Pocitos Nuevo", "Montevideo"))
        self.assertEqual(split_location("Montevideo"), (None, "Montevideo"))

    def test_title_hints(self):
        self.assertEqual(title_hint("Toyota Hilux 2.8 Srx 4x4 At", TRANSMISSION_HINTS), "automatica")
        self.assertEqual(title_hint("Fiat Uno 1.4 Manual", TRANSMISSION_HINTS), "manual")
        self.assertIsNone(title_hint("Volkswagen Gol 1.6 Trendline", TRANSMISSION_HINTS))
        self.assertEqual(title_hint("Peugeot 208 Hdi Diésel", FUEL_HINTS), "diesel")
        self.assertEqual(title_hint("Toyota Corolla Híbrido", FUEL_HINTS), "hibrido")

    def test_static_page_without_results(self):
        html = ('<script id="__NORDIC_RENDERING_CTX__">_n.ctx.r={"title":"x","flags":'
                '{"staticMarkup":true}};</script>')
        self.assertIsNone(parse_page(html))

    def test_model_from_title(self):
        modelos = ["Aveo", "Aveo G3", "Onix", "Onix Plus"]
        self.assertEqual(model_from_title("Chevrolet Aveo G3 2012 1.6", "Chevrolet", modelos), "Aveo G3")
        self.assertEqual(model_from_title("Chevrolet Onix 2020 Lt", "Chevrolet", modelos), "Onix")
        self.assertIsNone(model_from_title("Chevrolet Cruze 2018", "Chevrolet", modelos))

    def test_version(self):
        self.assertEqual(version_from_title("Volkswagen Gol 2013 1.6 Trendline", "Volkswagen", "Gol", 2013),
                         "1.6 Trendline")
        self.assertIsNone(version_from_title("Volkswagen Gol 2016 -", "Volkswagen", "Gol", 2016))


class TestSavedPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        files = sorted(RAW_DIR.glob("feasibility_vw_gol_*.html"))
        if not files:
            raise unittest.SkipTest("no hay HTML guardado en data/raw/")
        cls.page = parse_page(files[-1].read_text(encoding="utf-8"))

    def test_page(self):
        self.assertIsNotNone(self.page)
        self.assertEqual(len(self.page["cards"]), 48)
        self.assertGreater(self.page["total"], 48)
        self.assertIn("seller_type", self.page["filters"])
        self.assertIn("VEHICLE_YEAR", self.page["filters"])
        for flt in self.page["filters"].values():
            for v in flt["values"]:
                self.assertNotIn("_NoIndex_True", v["url"] or "")

    def test_rows(self):
        rows = [parse_card(c, "Volkswagen", "Gol", "particular", "test", "2026-10-28", 2026)
                for c in self.page["cards"]]
        self.assertEqual(len({r["item_id"] for r in rows}), 48)
        for r in rows:
            self.assertEqual(list(r), COLUMNS)
            self.assertTrue(r["item_id"].startswith("MLU"))
            self.assertTrue(r["url"].startswith("https://auto.mercadolibre.com.uy/"))
            self.assertIsInstance(r["precio"], (int, float))
            self.assertIn(r["moneda"], ("USD", "UYU"))
            self.assertTrue(1950 <= r["anio"] <= 2027)
            self.assertIsNotNone(r["departamento"])
        first = rows[0]
        self.assertEqual((first["anio"], first["km"], first["precio"]), (2013, 86000, 11300))
        self.assertEqual((first["barrio"], first["departamento"]), ("Pocitos Nuevo", "Montevideo"))
        self.assertEqual(sum(r["tienda_oficial"] for r in rows), 7)


if __name__ == "__main__":
    unittest.main()
