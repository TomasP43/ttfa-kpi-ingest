"""Cliente mínimo de Microsoft Graph para leer mails y descargar adjuntos.

Autenticación: flujo client_credentials (app-only). La app usa su propio
secreto (registrada en Azure AD) — NO la contraseña del usuario del buzón.

Permisos Graph requeridos:
- Mail.Read   (siempre)
- Mail.ReadWrite (solo si MARK_AS_READ=true)

Recomendado en producción: aplicar una Application Access Policy para limitar
la app a un solo buzón (ver docs/SETUP_AZURE.md).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Tuple

import msal
import requests

from .config import GraphSettings

log = logging.getLogger(__name__)

_GRAPH = "https://graph.microsoft.com/v1.0"
_SCOPE = ["https://graph.microsoft.com/.default"]


@dataclass(frozen=True)
class Message:
    id: str
    subject: str
    received: str  # ISO-8601 con TZ (lo que devuelve Graph en receivedDateTime)
    sender: str
    has_attachments: bool

    @property
    def received_dt(self) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(self.received.replace("Z", "+00:00"))
        except ValueError:
            return None


@dataclass(frozen=True)
class Attachment:
    id: str
    name: str
    content: bytes


class GraphError(RuntimeError):
    """Error genérico de Graph (autenticación, HTTP, etc.)."""


class GraphClient:
    def __init__(self, settings: GraphSettings, session: Optional[requests.Session] = None):
        self.settings = settings
        self._session = session or requests.Session()
        self._app = msal.ConfidentialClientApplication(
            client_id=settings.client_id,
            client_credential=settings.client_secret,
            authority=f"https://login.microsoftonline.com/{settings.tenant_id}",
        )
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0

    # ------------------------------------------------------------------- auth

    def _get_token(self) -> str:
        # Cachito de cache local; msal también cachea, así evitamos llamadas
        # extra cuando el run procesa varios mails seguidos.
        now = datetime.now(timezone.utc).timestamp()
        if self._token and now < self._token_expiry - 60:
            return self._token

        result = self._app.acquire_token_silent(_SCOPE, account=None) or self._app.acquire_token_for_client(_SCOPE)
        if not result or "access_token" not in result:
            err = (result or {}).get("error_description") or result
            raise GraphError(f"No se pudo obtener token de Graph: {err}")
        self._token = result["access_token"]
        self._token_expiry = now + int(result.get("expires_in", 3600))
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._get_token()}", "Accept": "application/json"}

    def _request(self, method: str, url: str, **kw) -> requests.Response:
        r = self._session.request(method, url, headers=self._headers(), timeout=60, **kw)
        if r.status_code >= 400:
            raise GraphError(
                f"Graph {method} {url} → HTTP {r.status_code}: {r.text[:500]}"
            )
        return r

    # --------------------------------------------------------------- mensajes

    def find_messages(
        self,
        sender: str,
        subject_prefix: str,
        lookback_days: int,
        mailbox: Optional[str] = None,
    ) -> List[Message]:
        """Lista mails recientes de `sender` cuyo asunto empieza con `subject_prefix`.

        Filtra por fecha en Graph para no traer todo el buzón. El filtro de
        prefijo de asunto se aplica en cliente (startswith es case-sensitive en
        Graph y los asuntos vienen con variaciones de mayúsculas).
        """
        mailbox = mailbox or self.settings.mailbox
        since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        # OData filter: por remitente y fecha. El asunto lo filtramos abajo.
        filter_q = (
            f"receivedDateTime ge {since} "
            f"and from/emailAddress/address eq '{sender}' "
            f"and hasAttachments eq true"
        )
        url = (
            f"{_GRAPH}/users/{mailbox}/messages"
            f"?$filter={requests.utils.quote(filter_q)}"
            f"&$select=id,subject,receivedDateTime,from,hasAttachments"
            f"&$top=50&$orderby=receivedDateTime desc"
        )

        msgs: List[Message] = []
        prefix_norm = subject_prefix.strip().lower()
        while url:
            r = self._request("GET", url)
            data = r.json()
            for item in data.get("value", []):
                subject = item.get("subject") or ""
                if prefix_norm and not subject.strip().lower().startswith(prefix_norm):
                    continue
                from_addr = (
                    (item.get("from") or {}).get("emailAddress", {}).get("address") or ""
                )
                msgs.append(
                    Message(
                        id=item["id"],
                        subject=subject,
                        received=item.get("receivedDateTime", ""),
                        sender=from_addr,
                        has_attachments=bool(item.get("hasAttachments")),
                    )
                )
            url = data.get("@odata.nextLink")
        log.info(
            "graph: %d mensaje(s) de %s con asunto que empieza con %r en últimos %d días",
            len(msgs),
            sender,
            subject_prefix,
            lookback_days,
        )
        return msgs

    # -------------------------------------------------------------- adjuntos

    def _list_attachments(self, message_id: str, mailbox: Optional[str] = None) -> List[dict]:
        mailbox = mailbox or self.settings.mailbox
        url = (
            f"{_GRAPH}/users/{mailbox}/messages/{message_id}/attachments"
            f"?$select=id,name,size,contentType"
        )
        r = self._request("GET", url)
        return r.json().get("value", [])

    def _download(self, message_id: str, attachment_id: str, mailbox: Optional[str] = None) -> bytes:
        mailbox = mailbox or self.settings.mailbox
        url = f"{_GRAPH}/users/{mailbox}/messages/{message_id}/attachments/{attachment_id}/$value"
        r = self._request("GET", url)
        return r.content

    def download_attachment(
        self, message_id: str, name: str, mailbox: Optional[str] = None
    ) -> Optional[Attachment]:
        """Busca un adjunto por nombre (substring case-insensitive) y lo descarga."""
        target = name.strip().lower()
        for att in self._list_attachments(message_id, mailbox=mailbox):
            if target in (att.get("name") or "").lower():
                content = self._download(message_id, att["id"], mailbox=mailbox)
                return Attachment(id=att["id"], name=att["name"], content=content)
        return None

    def download_attachment_by_pattern(
        self, message_id: str, pattern: str, mailbox: Optional[str] = None
    ) -> Optional[Attachment]:
        """Como download_attachment pero matchea con regex (re.search, IGNORECASE)."""
        rx = re.compile(pattern, re.IGNORECASE)
        for att in self._list_attachments(message_id, mailbox=mailbox):
            name = att.get("name") or ""
            if rx.search(name):
                content = self._download(message_id, att["id"], mailbox=mailbox)
                return Attachment(id=att["id"], name=name, content=content)
        return None

    # ----------------------------------------------------------- marcar leído

    def mark_read(self, message_id: str, mailbox: Optional[str] = None) -> None:
        if not self.settings.mark_as_read:
            return
        mailbox = mailbox or self.settings.mailbox
        url = f"{_GRAPH}/users/{mailbox}/messages/{message_id}"
        self._request("PATCH", url, json={"isRead": True})
