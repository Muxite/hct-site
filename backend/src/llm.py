"""Minimal OpenRouter chat client (OpenAI-compatible /chat/completions).

Defaults to Gemini 3 Flash Preview (cheap, large context). Kept tiny on purpose
— one ``complete()`` call — so it's trivial to mock in tests (pass a pre-built
``httpx.Client`` with a MockTransport, or substitute a fake object with a
``complete`` method). Token/latency usage from each call is recorded on an
optional :class:`UsageTracker` for the experimentation + metrics tooling.
"""

from __future__ import annotations

import time

import httpx

from src.metrics import UsageTracker


class LLMError(RuntimeError):
    """Raised when the LLM call fails or returns no usable content."""


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = "google/gemini-3-flash-preview",
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 120.0,
        client: httpx.Client | None = None,
        tracker: UsageTracker | None = None,
    ) -> None:
        self.model = model
        self.tracker = tracker
        self._base = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # OpenRouter attribution headers (optional but recommended).
            "HTTP-Referer": "https://hct-lab.github.io/",
            "X-Title": "hct-manager",
        }
        self._client = client or httpx.Client(base_url=self._base, timeout=timeout)

    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        json_mode: bool = True,
        label: str = "",
    ) -> str:
        """Send a system+user prompt, return the assistant message text.

        ``label`` tags the recorded :class:`~src.metrics.CallRecord` so
        the metrics log can attribute tokens to a stage (extract/describe/...).
        """

        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        started = time.monotonic()
        try:
            resp = self._client.post(
                "/chat/completions", headers=self._headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            self._track(None, started, label, ok=False)
            raise LLMError(f"OpenRouter request failed: {exc}") from exc

        self._track(data.get("usage"), started, label, ok=True)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"OpenRouter returned no content: {data!r}") from exc
        if not content or not content.strip():
            raise LLMError("OpenRouter returned empty content")
        return content

    def _track(self, usage: dict | None, started: float, label: str, *, ok: bool) -> None:
        if self.tracker is not None:
            self.tracker.record(
                model=self.model,
                usage=usage,
                latency_s=time.monotonic() - started,
                label=label or None,
                ok=ok,
            )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OpenRouterClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
