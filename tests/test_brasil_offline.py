"""Tests offline del parser de Brasil.

Confirma:
- Filtro por compañía TTFA → 0 daños en el sample (plantilla vacía).
- Filtro por compañía AUTOPORT → 2 daños (sirve de control de que el parser
  realmente lee los bloques y no devuelve cero por bug).
- Extracción de fecha desde el nombre del archivo (DDMMYYYY y DD-MM-YYYY).
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.parsers import brasil  # noqa: E402
from tests._sample_factory import build_brasil_sample  # noqa: E402


SAMPLE = ROOT / "samples" / "brasil_sample.xlsx"


def _load_sample_bytes() -> tuple[bytes, str]:
    if SAMPLE.exists():
        return SAMPLE.read_bytes(), f"samples/{SAMPLE.name}"
    return build_brasil_sample(), "<sintético en memoria>"


class TestBrasilParser(unittest.TestCase):
    def setUp(self):
        self.data, self.origin = _load_sample_bytes()
        self.report_date = date(2026, 6, 8)
        print(f"\n[brasil] usando muestra: {self.origin}")

    def test_ttfa_cero_danos(self):
        records = brasil.parse(self.data, report_date=self.report_date, company="TTFA")
        self.assertEqual(len(records), 0, f"TTFA debería tener 0 daños, vino {len(records)}")

    def test_autoport_dos_danos_como_control(self):
        records = brasil.parse(self.data, report_date=self.report_date, company="AUTOPORT")
        self.assertEqual(
            len(records), 2,
            f"AUTOPORT debería tener exactamente 2 filas reales, vinieron {len(records)}",
        )
        # Cada fila debe traer Fleet N°, VIN y Cause con contenido.
        for r in records:
            self.assertTrue(r.get("Fleet N°"), "Fleet N° vacío en una fila AUTOPORT")
            self.assertTrue(r.get("VIN"), "VIN vacío en una fila AUTOPORT")
            self.assertTrue(r.get("Cause"), "Cause vacío en una fila AUTOPORT")
            self.assertEqual(r.get("Fecha"), self.report_date)
            self.assertEqual(r.get("Fecha de descarga"), self.report_date)

    def test_row_key_estable_y_unico(self):
        records = brasil.parse(self.data, report_date=self.report_date, company="AUTOPORT")
        keys = [r["__row_key__"] for r in records]
        self.assertEqual(len(keys), len(set(keys)), "Las row_key deben ser únicas en el lote")
        # Re-parsear da las mismas claves (determinístico).
        records2 = brasil.parse(self.data, report_date=self.report_date, company="AUTOPORT")
        self.assertEqual([r["__row_key__"] for r in records2], keys)

    def test_fecha_desde_nombre_ddmmyyyy_sin_separadores(self):
        d = brasil.date_from_filename("Reporte_de_Da_os_y_equipos_descargados_08062026_.xlsx")
        self.assertEqual(d, date(2026, 6, 8))

    def test_fecha_desde_nombre_con_separadores(self):
        self.assertEqual(
            brasil.date_from_filename("Reporte de Daños 08-06-2026.xlsx"),
            date(2026, 6, 8),
        )
        self.assertEqual(
            brasil.date_from_filename("Reporte de Daños 2026-06-08.xlsx"),
            date(2026, 6, 8),
        )

    def test_fecha_fallback_a_recepcion(self):
        d, src = brasil.resolve_report_date(
            "archivo_sin_fecha.xlsx",
            received_iso="2026-06-09T10:00:00Z",
        )
        self.assertEqual(src, "received")
        self.assertEqual(d, date(2026, 6, 9))


if __name__ == "__main__":
    unittest.main(verbosity=2)
