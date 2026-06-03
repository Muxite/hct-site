"""Per-source fingerprint state for change detection.

Each watched source gets a small JSON file under the state dir (default
``assets/state/``) recording the last seen scrape ``fingerprint`` plus a little
metadata. Before running the (costly) LLM step, the manager compares the fresh
fingerprint to the stored one and skips sources that have not changed.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

_SAFE = re.compile(r"[^a-z0-9_-]+")


def _safe_key(key: str) -> str:
    """Sanitize a source key into a safe filename stem."""

    stem = _SAFE.sub("-", key.strip().lower()).strip("-")
    if not stem:
        raise ValueError(f"invalid source key: {key!r}")
    return stem


class StateStore:
    """Reads/writes per-source state JSON files under ``dir``."""

    def __init__(self, dir: str | os.PathLike[str]) -> None:
        self.dir = Path(dir)

    def _path(self, key: str) -> Path:
        return self.dir / f"{_safe_key(key)}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        """Return the stored state dict for ``key``, or None if never seen."""

        path = self._path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def fingerprint(self, key: str) -> str | None:
        """Return the last stored fingerprint for ``key`` (or None)."""

        state = self.get(key)
        return state.get("fingerprint") if state else None

    def changed(self, key: str, fingerprint: str) -> bool:
        """True if ``fingerprint`` differs from the stored one (or none stored).

        An empty/blank fingerprint is treated as "changed" so a failed/empty
        scrape never silently masks a real update.
        """

        if not fingerprint:
            return True
        return self.fingerprint(key) != fingerprint

    def update(self, key: str, fingerprint: str, **extra: Any) -> dict[str, Any]:
        """Atomically persist the latest fingerprint (+ optional metadata)."""

        state: dict[str, Any] = {
            "key": key,
            "fingerprint": fingerprint,
            "updated_at": time.time(),
            **extra,
        }
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return state
