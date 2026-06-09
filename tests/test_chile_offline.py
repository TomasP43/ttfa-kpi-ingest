"""Tests offline del parser de Chile.

Si existe samples/chile_sample.xlsx, lo usa. Si no, genera uno sintético con la
misma forma (la primera vez es lo esperable hasta que el equipo deje un real
anonimizado).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.parsers import chile  # noqa: E402
from tests._sample_factory import build_chile_sample  # noqa: E402


SAMPLE = ROOT / "samples" / "chile_sample.xlsx"


def _load_sample_bytes() -> tuple[bytes, str]:
    if SAMPLE.exists():
        return SAMPLE.read_bytes(), f"samples/{SAMPLE.name}"
    return build_chile_sample(), "<sintético en memoria>"


class TestChileParser(unittest.TestCase):
    def setUp(self):
        self.data, self.origin = _load_sample_bytes()
        print(f"\n[chile] usando muestra: {self.origin}")

    def test_columnas_y_orden(self):
        records = chile.parse(self.data)
        self.assertGreater(len(records), 0, "El sample está vacío")
        # Todas las filas deben tener todas las columnas esperadas.
        for r in records[:5]:
            self.assertEqual(list(r.keys()), chile.COLUMNS)

    def test_dedup_filtra_id_inspection_repetidos(self):
        records = chile.parse(self.data)
        # filter_new contra un set vacío debe deduplicar al menos los repetidos
        # dentro del propio archivo.
        keys = [r[chile.DEDUP_KEY] for r in records]
        unicos = chile.filter_new(records, known=set())
        self.assertEqual(
            len(unicos),
            len(set(keys)),
            "filter_new debería devolver una fila por ID_Inspection único",
        )

    def test_dedup_respeta_estado_conocido(self):
        records = chile.parse(self.data)
        # Marcamos como conocida la primera clave: tras dedup no debería volver.
        first_key = records[0][chile.DEDUP_KEY]
        nuevos = chile.filter_new(records, known={first_key})
        self.assertTrue(all(r[chile.DEDUP_KEY] != first_key for r in nuevos))


if __name__ == "__main__":
    unittest.main(verbosity=2)
