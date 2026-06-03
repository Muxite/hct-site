"""Minimal Supabase (PostgREST) write client for the backend.

We only need to push rows into a handful of tables, so rather than pull in the
full ``supabase`` SDK we talk to the auto-generated REST API directly over
httpx — same tiny-client style as ``llm.py`` and ``ujin_client.py``. Auth is the
project **secret** key (falls back to the legacy service-role key); both bypass
RLS, so the backend can write while the public site stays read-only.

Pass a pre-built ``httpx.Client`` (e.g. with a MockTransport) for testing.
"""

from __future__ import annotations

from typing import Any, Sequence

import httpx


class SupabaseError(RuntimeError):
    """Raised when a Supabase REST call fails."""


class SupabaseClient:
    def __init__(
        self,
        url: str,
        key: str,
        *,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not url or not key:
            raise SupabaseError("Supabase URL and key are required")
        self._base = url.rstrip("/") + "/rest/v1"
        self._key = key
        self._client = client or httpx.Client(timeout=timeout)

    def _headers(self, *, prefer: str = "") -> dict[str, str]:
        h = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        if prefer:
            h["Prefer"] = prefer
        return h

    def select(
        self, table: str, *, columns: str = "*", params: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """Read rows from ``table``. ``params`` are PostgREST query filters."""

        q = {"select": columns, **(params or {})}
        try:
            resp = self._client.get(
                f"{self._base}/{table}", params=q, headers=self._headers()
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise SupabaseError(f"select from {table} failed: {exc}") from exc

    def upsert(
        self,
        table: str,
        rows: Sequence[dict[str, Any]],
        *,
        on_conflict: str | None = None,
    ) -> int:
        """Insert-or-update ``rows`` into ``table``. Returns the row count sent.

        ``on_conflict`` is the unique column used to merge duplicates (e.g.
        ``slug`` for publications, ``key`` for site_content).
        """

        rows = list(rows)
        if not rows:
            return 0
        params = {"on_conflict": on_conflict} if on_conflict else {}
        try:
            resp = self._client.post(
                f"{self._base}/{table}",
                params=params,
                headers=self._headers(prefer="resolution=merge-duplicates,return=minimal"),
                json=rows,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise SupabaseError(f"upsert into {table} failed: {exc}") from exc
        return len(rows)

    def delete_all(self, table: str, *, key: str) -> None:
        """Delete every row in ``table`` (filter on ``key`` is not null).

        PostgREST refuses an unfiltered DELETE, so we filter on the primary/unique
        column being non-null, which matches all rows.
        """

        try:
            resp = self._client.delete(
                f"{self._base}/{table}",
                params={key: "not.is.null"},
                headers=self._headers(prefer="return=minimal"),
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise SupabaseError(f"delete from {table} failed: {exc}") from exc

    def replace(self, table: str, rows: Sequence[dict[str, Any]], *, key: str) -> int:
        """Full sync: clear ``table`` then insert ``rows``. Returns rows written."""

        self.delete_all(table, key=key)
        rows = list(rows)
        if not rows:
            return 0
        try:
            resp = self._client.post(
                f"{self._base}/{table}",
                headers=self._headers(prefer="return=minimal"),
                json=rows,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise SupabaseError(f"insert into {table} failed: {exc}") from exc
        return len(rows)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SupabaseClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
