"""Generadores de muestras sintéticas para los tests offline.

Los reales (anonimizados o no) se asume que se ponen en samples/. Si no están,
los tests construyen muestras en memoria con la misma estructura para validar
que el parser sigue funcionando.
"""

from __future__ import annotations

import io

from openpyxl import Workbook

from app.parsers.chile import COLUMNS as CHILE_COLUMNS


def build_chile_sample() -> bytes:
    """Sample sintético: 4 filas con duplicado intencional por ID_Inspection."""
    wb = Workbook()
    ws = wb.active
    ws.title = "ARRIBOS"
    ws.append(CHILE_COLUMNS)

    def _row(vin, id_arribo, id_inspection, dano="N", parte=None, tipo=None):
        return [
            vin, id_arribo, id_inspection, "Hilux", "A1",
            "2025-06-01", 2823, "True", "TASA", dano,
            parte, tipo, None, None, None,
            "Sin daños", None, "Sin daños", None,
        ]

    # Tres filas distintas + una repetida (mismo ID_Inspection que la primera).
    ws.append(_row("8AJDB3CD3S1377001", "5e17f397", "insp-001"))
    ws.append(_row("8AJDB3CD3S1377002", "5e17f397", "insp-002"))
    ws.append(_row("8AJDB3CD3S1377003", "5e17f397", "insp-003", dano="S", parte="Paragolpe", tipo="Rayón"))
    ws.append(_row("8AJDB3CD3S1377001", "5e17f397", "insp-001"))  # duplicado

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_brasil_sample() -> bytes:
    """Sample sintético reproduciendo la estructura por bloques.

    - Bloque TRANSPORTE FURLONG: todo vacío (plantilla).
    - Bloque TTFA: todo vacío (queremos confirmar que devuelve 0 daños).
    - Bloque AUTOPORT: 2 filas con datos reales (control).
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "DAÑOS"

    header = ["#", "EQUIPO", "COMPANIA", "VIN", "DAÑO", "OBSERVACIONES"]

    def write_block(company: str, filled: list[tuple] | None = None, total_rows: int = 5):
        ws.append(["REPORTE DE  DAÑOS POR COMPANIA"])
        ws.append([])
        ws.append(header)
        filled = filled or []
        filled_dict = {row[0]: row for row in filled}
        for i in range(1, total_rows + 1):
            if i in filled_dict:
                _, equipo, vin, dano, obs = filled_dict[i]
                ws.append([i, equipo, company, vin, dano, obs])
            else:
                ws.append([i, None, company, None, None, None])
        # Fila total: '#' vacío, todo None salvo conteo en DAÑO.
        ws.append([None, None, None, None, len([r for r in filled if r[3]]), None])
        ws.append([])

    write_block("TRANSPORTE FURLONG", filled=[], total_rows=5)
    write_block("TTFA", filled=[], total_rows=5)
    write_block(
        "AUTOPORT",
        filled=[
            (1, 1056, "9BRKZAAG0T0771782", "Avería luneta trasera y tapa baúl", None),
            (2, 1056, "9BRKB3F39V8394976", "Avería paragolpe trasero y tapa baúl", None),
        ],
        total_rows=5,
    )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
