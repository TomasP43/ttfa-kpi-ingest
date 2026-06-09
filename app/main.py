"""Orquestador del servicio: corre las dos fuentes (Chile y Brasil)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from . import config
from .graph_client import GraphClient, Message
from .parsers import brasil, chile
from .state import StateStore
from .writer import append_rows


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


log = logging.getLogger("ttfa-kpi-ingest")


# =============================================================================
# CHILE
# =============================================================================

def run_chile(
    settings: config.Settings, client: GraphClient, store: StateStore
) -> int:
    """Procesa todos los mails nuevos de la fuente Chile. Devuelve filas agregadas."""
    log.info("=== CHILE: buscando mails de %s ===", settings.chile.sender)
    msgs = client.find_messages(
        sender=settings.chile.sender,
        subject_prefix=settings.chile.subject_prefix,
        lookback_days=settings.lookback_days,
    )
    if not msgs:
        log.info("chile: sin mails que procesar")
        return 0

    total_added = 0
    out_path = Path(settings.output_dir) / "pegar_chile.xlsx"
    for msg in msgs:
        if store.message_seen(msg.id):
            log.info("chile: mail ya procesado, salteando (%s)", msg.subject)
            continue
        log.info("chile: procesando %r recibido %s", msg.subject, msg.received)
        attach = client.download_attachment(msg.id, settings.chile.attachment_name)
        if attach is None:
            log.warning(
                "chile: el mail no trae el adjunto esperado %r — se ignora",
                settings.chile.attachment_name,
            )
            store.mark_message(msg.id)
            continue

        try:
            records = chile.parse(attach.content, sheet_name=settings.chile.sheet)
        except chile.ChileParseError as exc:
            log.error("chile: error parseando %s: %s", attach.name, exc)
            continue  # NO marcamos como visto — queremos reintentar al arreglar el origen

        known = store.known_keys("chile")
        nuevos = chile.filter_new(records, known)
        log.info("chile: %d filas en el archivo, %d nuevas tras dedup", len(records), len(nuevos))

        if nuevos:
            append_rows(
                path=out_path,
                sheet_name="Pegar Chile",
                columns=chile.COLUMNS,
                rows=chile.records_to_rows(nuevos),
            )
            store.add_keys("chile", (r[chile.DEDUP_KEY] for r in nuevos))
            total_added += len(nuevos)

        store.mark_message(msg.id)
        client.mark_read(msg.id)

    store.save()
    log.info("=== CHILE: total filas nuevas %d ===", total_added)
    return total_added


# =============================================================================
# BRASIL
# =============================================================================

def run_brasil(
    settings: config.Settings, client: GraphClient, store: StateStore
) -> int:
    log.info("=== BRASIL: buscando mails de %s ===", settings.brasil.sender)
    msgs = client.find_messages(
        sender=settings.brasil.sender,
        subject_prefix=settings.brasil.subject_prefix,
        lookback_days=settings.lookback_days,
    )
    if not msgs:
        log.info("brasil: sin mails que procesar")
        return 0

    total_added = 0
    out_path = Path(settings.output_dir) / "brasil_impo_db.xlsx"
    for msg in msgs:
        if store.message_seen(msg.id):
            log.info("brasil: mail ya procesado, salteando (%s)", msg.subject)
            continue
        log.info("brasil: procesando %r recibido %s", msg.subject, msg.received)
        attach = client.download_attachment_by_pattern(
            msg.id, settings.brasil.attachment_pattern
        )
        if attach is None:
            log.warning(
                "brasil: el mail no trae adjunto que matchee %r — se ignora",
                settings.brasil.attachment_pattern,
            )
            store.mark_message(msg.id)
            continue

        report_date, src = brasil.resolve_report_date(attach.name, msg.received)
        log.info("brasil: fecha del reporte = %s (fuente: %s)", report_date.isoformat(), src)

        try:
            records = brasil.parse(
                attach.content,
                report_date=report_date,
                company=settings.brasil.company,
                sheet_name=settings.brasil.sheet,
            )
        except brasil.BrasilParseError as exc:
            log.error("brasil: error parseando %s: %s", attach.name, exc)
            continue

        known = store.known_keys("brasil")
        nuevos = brasil.filter_new(records, known)
        log.info(
            "brasil: %d filas leídas, %d nuevas tras dedup",
            len(records),
            len(nuevos),
        )

        if nuevos:
            append_rows(
                path=out_path,
                sheet_name="Brasil Impo DB",
                columns=brasil.IMPO_COLUMNS,
                rows=brasil.records_to_rows(nuevos),
            )
            store.add_keys("brasil", brasil.keys_of(nuevos))
            total_added += len(nuevos)

        store.mark_message(msg.id)
        client.mark_read(msg.id)

    store.save()
    log.info("=== BRASIL: total filas nuevas %d ===", total_added)
    return total_added


# =============================================================================
# Entry point
# =============================================================================

def main(argv: Optional[list[str]] = None) -> int:
    _setup_logging()
    try:
        settings = config.load_settings(require_graph=True)
    except config.ConfigError as exc:
        log.error("Configuración inválida: %s", exc)
        return 2

    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.downloads_dir).mkdir(parents=True, exist_ok=True)

    assert settings.graph is not None  # require_graph=True ⇒ existe
    client = GraphClient(settings.graph)
    store = StateStore(settings.state_path)

    log.info(
        "Arrancando ingesta: buzón=%s, lookback=%d días, marcar leído=%s",
        settings.graph.mailbox,
        settings.lookback_days,
        settings.graph.mark_as_read,
    )

    errors = 0
    try:
        run_chile(settings, client, store)
    except Exception:
        log.exception("chile: error inesperado en la corrida")
        errors += 1
    try:
        run_brasil(settings, client, store)
    except Exception:
        log.exception("brasil: error inesperado en la corrida")
        errors += 1

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
