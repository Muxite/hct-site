"""Supabase Storage download — plain ``httpx`` GET against the Storage REST API.

Mirrors ``figures.py``'s minimal upload client (bucket + object path, secret
key as bearer token) but for the read direction: pulling a private object
(the admin-uploaded CV docx) down to a local path so it can be dropped into
the inbox for the existing CV pipeline to pick up. No dependency on
``SupabaseClient``/PostgREST — Storage has its own REST surface, not the
``rest/v1`` one ``supabase_client.py`` talks to.
"""

from __future__ import annotations

from pathlib import Path

import httpx


class StorageError(RuntimeError):
    """Raised when a Supabase Storage download fails."""


def download_object(
    sb_url: str,
    sb_secret_key: str,
    bucket: str,
    object_path: str,
    dest: str | Path,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> Path:
    """GET ``{bucket}/{object_path}`` from Supabase Storage and write it to ``dest``.

    Auth is the secret key as a bearer token — bypasses the bucket's
    admin-write-only RLS the same way ``SupabaseClient`` bypasses table RLS
    everywhere else in this backend (this never runs under an authenticated
    admin session; see ``db/schema.sql``'s ``cv-uploads admin all`` policy,
    which only constrains *authenticated* access). Pass a pre-built
    ``httpx.Client`` (e.g. with a ``MockTransport``) for testing; otherwise a
    short-lived client is created and closed for this one call.

    Returns ``dest`` (as a ``Path``) on success. Creates ``dest``'s parent
    directory if needed. Raises :class:`StorageError` on a missing
    URL/key or any HTTP failure (network error, 404, etc.).
    """

    if not sb_url or not sb_secret_key:
        raise StorageError("Supabase URL and secret key are required")

    url = f"{sb_url.rstrip('/')}/storage/v1/object/{bucket}/{object_path}"
    headers = {"apikey": sb_secret_key, "Authorization": f"Bearer {sb_secret_key}"}

    owns_client = client is None
    http = client or httpx.Client(timeout=timeout)
    try:
        resp = http.get(url, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise StorageError(f"download of {bucket}/{object_path} failed: {exc}") from exc
    finally:
        if owns_client:
            http.close()

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return dest
