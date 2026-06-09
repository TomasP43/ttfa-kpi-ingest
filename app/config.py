"""Carga y valida la configuración del servicio desde variables de entorno.

Toda la operación es por .env: Nico (deploy) solo edita ese archivo, nunca el
código. Si falta algo crítico, se reporta con un mensaje claro al arrancar.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

# Carga .env si existe (en local). En Docker las vars vienen por env_file.
load_dotenv()


def _get(name: str, default: Optional[str] = None) -> Optional[str]:
    """Lee una variable de entorno devolviendo None si está vacía."""
    val = os.environ.get(name, default)
    if val is None:
        return None
    val = val.strip()
    return val or None


def _get_bool(name: str, default: bool = False) -> bool:
    raw = _get(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "y", "si", "sí"}


def _get_int(name: str, default: int) -> int:
    raw = _get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} debe ser entero, recibido: {raw!r}")


class ConfigError(RuntimeError):
    """Error de configuración (faltan vars o tienen valores inválidos)."""


@dataclass(frozen=True)
class GraphSettings:
    tenant_id: str
    client_id: str
    client_secret: str
    mailbox: str
    mark_as_read: bool


@dataclass(frozen=True)
class ChileSettings:
    sender: str
    subject_prefix: str
    attachment_name: str
    sheet: str


@dataclass(frozen=True)
class BrasilSettings:
    sender: str
    subject_prefix: str
    attachment_pattern: str
    sheet: str
    company: str


@dataclass(frozen=True)
class Settings:
    graph: Optional[GraphSettings]
    chile: ChileSettings
    brasil: BrasilSettings
    lookback_days: int
    state_path: str
    output_dir: str
    downloads_dir: str


def load_settings(require_graph: bool = True) -> Settings:
    """Construye Settings desde el entorno.

    Si require_graph=False, no falla aunque falten credenciales Graph (útil para
    tests offline). En producción se llama con require_graph=True y se valida
    todo de antemano.
    """
    tenant = _get("MS_TENANT_ID")
    client_id = _get("MS_CLIENT_ID")
    client_secret = _get("MS_CLIENT_SECRET")
    mailbox = _get("MS_MAILBOX")

    graph: Optional[GraphSettings]
    missing = [
        name
        for name, val in (
            ("MS_TENANT_ID", tenant),
            ("MS_CLIENT_ID", client_id),
            ("MS_CLIENT_SECRET", client_secret),
            ("MS_MAILBOX", mailbox),
        )
        if not val
    ]
    if missing:
        if require_graph:
            raise ConfigError(
                "Faltan variables de Microsoft Graph en el entorno: "
                + ", ".join(missing)
                + ". Copiá .env.example a .env y completalas (ver docs/SETUP_AZURE.md)."
            )
        graph = None
    else:
        graph = GraphSettings(
            tenant_id=tenant,  # type: ignore[arg-type]
            client_id=client_id,  # type: ignore[arg-type]
            client_secret=client_secret,  # type: ignore[arg-type]
            mailbox=mailbox,  # type: ignore[arg-type]
            mark_as_read=_get_bool("MARK_AS_READ", default=False),
        )

    chile = ChileSettings(
        sender=_get("CHILE_SENDER") or "Alexis.yanez@furlong.cl",
        subject_prefix=_get("CHILE_SUBJECT_PREFIX") or "Reporte tasa",
        attachment_name=_get("CHILE_ATTACHMENT_NAME") or "REPORTE DE ARRIBOS.xlsx",
        sheet=_get("CHILE_SHEET") or "ARRIBOS",
    )

    brasil = BrasilSettings(
        sender=_get("BRASIL_SENDER") or "ailen.deretich@furlong.com.ar",
        subject_prefix=_get("BRASIL_SUBJECT_PREFIX") or "REPORTE DAÑOS DESCARGAS",
        attachment_pattern=_get("BRASIL_ATTACHMENT_PATTERN") or r"Reporte de Da.os.*\.xlsx$",
        sheet=_get("BRASIL_SHEET") or "DAÑOS",
        company=(_get("BRASIL_COMPANY") or "TTFA").upper(),
    )

    return Settings(
        graph=graph,
        chile=chile,
        brasil=brasil,
        lookback_days=_get_int("LOOKBACK_DAYS", default=14),
        state_path=_get("STATE_PATH") or "state/state.json",
        output_dir=_get("OUTPUT_DIR") or "output",
        downloads_dir=_get("DOWNLOADS_DIR") or "downloads",
    )
