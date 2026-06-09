"""Estado persistente del servicio: qué filas y qué mails ya se cargaron.

Se guarda en un solo JSON (state/state.json). Estructura:

    {
      "processed_keys": {
        "chile":  ["<ID_Inspection>", ...],
        "brasil": ["<row_key>",       ...]
      },
      "processed_messages": ["<message_id>", ...]
    }

Doble red de deduplicación:
- processed_keys evita pegar dos veces la misma fila aunque venga en mails distintos.
- processed_messages evita re-procesar el mismo mail aunque vuelva a aparecer en la
  búsqueda (LOOKBACK_DAYS).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Set


class StateStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self._keys: dict[str, Set[str]] = {"chile": set(), "brasil": set()}
        self._messages: Set[str] = set()
        self._load()

    # ------------------------------------------------------------------ I/O

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"El archivo de estado {self.path} está corrupto: {exc}. "
                "Revisalo a mano o borralo para empezar de cero."
            ) from exc

        keys = data.get("processed_keys") or {}
        for source, values in keys.items():
            self._keys.setdefault(source, set()).update(map(str, values))
        for mid in data.get("processed_messages") or []:
            self._messages.add(str(mid))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "processed_keys": {k: sorted(v) for k, v in self._keys.items()},
            "processed_messages": sorted(self._messages),
        }
        # Escritura atómica: primero a .tmp, después rename.
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    # ----------------------------------------------------------- claves de fila

    def known_keys(self, source: str) -> Set[str]:
        return set(self._keys.get(source, set()))

    def add_keys(self, source: str, keys: Iterable[str]) -> int:
        """Agrega claves al estado. Devuelve cuántas eran realmente nuevas."""
        target = self._keys.setdefault(source, set())
        before = len(target)
        for k in keys:
            if k:
                target.add(str(k))
        return len(target) - before

    # ---------------------------------------------------------------- mensajes

    def message_seen(self, message_id: str) -> bool:
        return message_id in self._messages

    def mark_message(self, message_id: str) -> None:
        self._messages.add(message_id)
