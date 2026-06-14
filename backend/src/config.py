"""Runtime configuration, loaded from environment variables.

Secrets (the OpenRouter key) come from ``keys.env`` which docker compose injects
into the container environment. Paths default to the repo layout but are
overridable so the same code runs in a container with volume mounts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Repo root = two levels up from this file (backend/src/config.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Lightest viable model for this task: cheap, 1M context, strong-enough JSON
# extraction + short summarization. Overridable via OPENROUTER_MODEL.
DEFAULT_MODEL = "google/gemini-3-flash-preview"
DEFAULT_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
DEFAULT_UJIN_URL = "http://ujin:8901"


@dataclass
class Config:
    openrouter_api_key: str
    model: str = DEFAULT_MODEL
    openrouter_base_url: str = DEFAULT_OPENROUTER_BASE
    ujin_url: str = DEFAULT_UJIN_URL
    scrape_mode: str = "article"
    # obscura headless renderer (binary baked into the backend image). Used to
    # render Google Scholar profiles to text — ujin's extractors drop the table's
    # authors/venue/year, but the rendered text carries it. Disable by clearing
    # OBSCURA_BIN; Scholar sources are then skipped rather than mis-extracted.
    obscura_bin: str = "obscura"
    obscura_wait: int = 6        # seconds to let the profile's JS settle
    obscura_timeout: int = 40
    data_dir: Path = _REPO_ROOT / "backend" / "data"
    # Google Scholar is an *optional secondary* source (the CV is primary) and
    # is off by default — scraping it trips CAPTCHAs. Opt in per run with
    # HCT_SCHOLAR_ENABLED=1; individual sources can still set `enabled:` in
    # sources.yaml to override either way.
    scholar_enabled: bool = False
    # Optional *rendered* static page for the legacy QA cross-check (looks for a
    # publications-static block). The live site is a React/Vite app and prose now
    # comes from site.yaml, so this is only used if HCT_INDEX_HTML points at a real
    # rendered snapshot; the Vite shell at this default path is ignored by QA.
    index_html: Path = _REPO_ROOT / "frontend" / "index.html"
    # Supabase is the single source of truth for site data (replaces the old
    # publications.yaml). Backend writes with the secret/service key.
    sb_url: str = ""
    sb_secret_key: str = ""       # SB_SEC_KEY (or SB_SERVICE_ROLE_KEY) — writes
    sb_publishable_key: str = ""  # SB_PUB_KEY — handed to the frontend (read-only)

    @property
    def templates_dir(self) -> Path:
        return self.data_dir / "templates"

    @property
    def examples_dir(self) -> Path:
        return self.data_dir / "examples"

    @property
    def sources_file(self) -> Path:
        return self.data_dir / "sources" / "sources.yaml"

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"

    @property
    def inputs_dir(self) -> Path:
        return self.data_dir / "inputs"

    @property
    def inbox_dir(self) -> Path:
        """User drop folder (volume-mounted): CV docx + people/research YAML."""
        return self.data_dir / "inbox"

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "Config":
        env = os.environ if environ is None else environ
        api_key = env.get("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set (expected in keys.env / environment)"
            )

        def path_env(name: str, default: Path) -> Path:
            val = env.get(name)
            return Path(val) if val else default

        return cls(
            openrouter_api_key=api_key,
            model=env.get("OPENROUTER_MODEL", DEFAULT_MODEL),
            openrouter_base_url=env.get("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE),
            ujin_url=env.get("UJIN_URL", DEFAULT_UJIN_URL),
            scrape_mode=env.get("HCT_SCRAPE_MODE", "article"),
            obscura_bin=env.get("OBSCURA_BIN", "obscura"),
            obscura_wait=int(env.get("OBSCURA_WAIT", "6")),
            obscura_timeout=int(env.get("OBSCURA_TIMEOUT", "40")),
            scholar_enabled=env.get("HCT_SCHOLAR_ENABLED", "").strip().lower()
            in {"1", "true", "yes"},
            data_dir=path_env("HCT_DATA_DIR", cls.data_dir),
            index_html=path_env("HCT_INDEX_HTML", cls.index_html),
            sb_url=env.get("SB_URL", "").strip().rstrip("/"),
            # New "secret" key preferred; legacy service-role key as fallback.
            sb_secret_key=(env.get("SB_SEC_KEY") or env.get("SB_SERVICE_ROLE_KEY") or "").strip(),
            sb_publishable_key=(env.get("SB_PUB_KEY") or env.get("SB_ANON_PUB_KEY") or "").strip(),
        )
