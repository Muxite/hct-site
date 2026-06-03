"""hct-manager — generate the HCT Lab site's Publications data.

Pipeline (one-shot): scrape lab Google Scholar profiles via the ujin service,
detect change by fingerprint, ask an LLM to turn the page into structured
per-paper records, validate them, and write ``frontend/data/publications.yaml``.
The frontend renders HTML from that YAML client-side.
"""

from src.models import Publication, PublicationSet, PubType, slug_for

__all__ = ["Publication", "PublicationSet", "PubType", "slug_for"]
__version__ = "0.1.0"
