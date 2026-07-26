"""A tiny localhost admin viewer for the Supabase data the agent writes.

This is **not** the public site — it's a server-rendered, read+edit SQL-style
viewer over the five tables (``publications``, ``timeline``, ``people``,
``research``, ``site_content``), one page per table, columns mirroring
``db/schema.sql``. Run it with ``hct-manager viewer``.

Edit routing follows the project's "YAML is the source of truth" rule:

* ``people`` / ``research`` are **written back to their YAML files** (so the
  viewer and ``hct-manager sync-content`` always agree on the record) *and*
  pushed straight to Supabase with a forced, single-row insert/update/delete
  (see ``_push_yaml_edit``/``_push_yaml_add``/``_push_yaml_delete``) — an
  explicit maintainer edit here always takes effect, it never depends on the
  bulk sync's fill-if-empty rule (see ``src.sync_content._bulk_sync``). That
  forced write is *narrow*, though: it only carries the columns this form
  actually edits (see ``_push_columns``), so fields it never asks about —
  ``people.bio``, ``research.summary``/``hero_image``, whatever the browser
  admin CMS wrote — are left untouched rather than nulled. The bulk resync
  still runs afterward too, only to propagate side effects of the YAML rewrite
  (like other rows' ``sort_order`` shifting), not to make the edit itself land.
* ``site_content`` is written back to its YAML file and re-synced via the
  bulk (additive-only) path — there's no per-row identity to key a forced
  single-row write off, unlike people/research.
* ``publications`` / ``timeline`` are AI/CV-generated, so their editable fields
  (``description``/``venue``/``link``/``bibtex`` and ``blurb``/``date_label``)
  are written **straight to Supabase** with the secret key. Note a later
  ``hct-manager describe --all`` / ``run`` can overwrite these.

FastAPI is an optional extra (``pip install -e .[viewer]``). This module is only
imported when the viewer actually runs (``hct-manager viewer`` imports it lazily
and turns a missing extra into a friendly install hint), so the core agent stays
dependency-light. The Supabase client and the three YAML paths are injected into
:func:`create_app`, so tests drive it with a fake client and temp files via
``fastapi.testclient`` — no network, consistent with the rest of the suite.

(FastAPI is imported at module scope on purpose: with ``from __future__ import
annotations`` it resolves route-handler type hints — notably ``Request`` — from
the *module* globals, so the imports can't be hidden inside ``create_app``.)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src import sync_content as sync_mod
from src.content import SiteContentError, SiteContent, load_site_yaml, dump_site_yaml
from src.models import Person, Publication, ResearchProject, TimelineEntry
from src.sync_content import (
    ContentError,
    _PEOPLE_KINDS,
    _RESEARCH_KINDS,
    dump_people_yaml,
    dump_research_yaml,
    load_people_yaml,
    load_research_yaml,
)

# Column order mirrors db/schema.sql so the viewer reads like the SQL tables.
# ``edit``: "yaml" -> write back to the YAML file + re-sync; "supabase" -> upsert
# the row directly. ``editable``: which columns a user may change. ``json``:
# columns whose values are dict/list (pretty-printed; edited as JSON).
TABLE_SPEC: dict[str, dict[str, Any]] = {
    "publications": {
        "columns": [
            "slug", "title", "authors", "year", "type", "venue", "link",
            "bibtex", "description", "updated_at",
        ],
        "pk": "slug",
        "edit": "supabase",
        "editable": ["description", "venue", "link", "bibtex"],
        "json": {"authors"},
    },
    "timeline": {
        "columns": ["position", "slug", "title", "authors", "year", "date_label", "blurb"],
        "pk": "position",
        "edit": "supabase",
        "editable": ["blurb", "date_label"],
        "json": {"authors"},
    },
    "people": {
        "columns": ["sort_order", "name", "role", "email", "photo", "kind"],
        "pk": "name",
        "edit": "yaml",
        "editable": ["name", "role", "email", "photo", "kind"],
        "addable": True,
        "json": set(),
    },
    "research": {
        "columns": ["sort_order", "title", "tagline", "description", "link", "image", "kind"],
        "pk": "title",
        "edit": "yaml",
        "editable": ["title", "tagline", "link", "image", "kind"],
        "addable": True,
        "json": set(),
    },
    "site_content": {
        "columns": ["key", "value"],
        "pk": "key",
        "edit": "yaml",
        "editable": ["value"],
        "json": {"value"},
    },
}

# Render these as <textarea> in edit forms (long prose / JSON), the rest as <input>.
TEXTAREA_FIELDS = {"description", "bibtex", "blurb", "value", "text"}

# The Supabase key column for each YAML-backed table -- ``name`` for people
# (immutable identity), ``slug`` for research (derived from the title, so it
# can change under an edit).
_KEY_COLUMN = {"people": "name", "research": "slug"}


def _push_columns(table: str) -> set[str]:
    """The columns the forced single-row push (``_push_yaml_edit``/``_add``) is
    allowed to write.

    ``_build_item`` only fills in the fields the edit form actually asks for,
    so a full ``item.row()`` (a ``model_dump``) also carries every *other*
    column as ``None`` -- ``people.bio``, ``research.description``/
    ``summary``/``hero_image``. Upserting that whole shape would write those
    nulls over whatever the browser admin CMS had put there, which is exactly
    the destruction ``sync_content``'s fill-if-empty rule
    (``_PEOPLE_FILL_FIELDS`` / ``_RESEARCH_FILL_FIELDS``) exists to prevent,
    just at a different seam. So the push sends only what this form genuinely
    owns: the editable columns, the row's key, and ``sort_order`` (which the
    viewer renumbers itself on every add/edit/delete).
    """

    return set(TABLE_SPEC[table]["editable"]) | {_KEY_COLUMN[table], "sort_order"}


def _push_payload(table: str, item: Any) -> dict[str, Any]:
    """``item.row()`` narrowed to :func:`_push_columns` -- see its docstring."""

    allowed = _push_columns(table)
    return {k: v for k, v in item.row().items() if k in allowed}


def _clean(v: Any) -> str | None:
    """Trim a form value to a string, mapping empty to None."""
    s = ("" if v is None else str(v)).strip()
    return s or None


def _cell(value: Any) -> str:
    """Jinja filter: render a cell value (dict/list -> JSON, None -> '')."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def create_app(
    *,
    supabase: Any,
    people_path: str | Path,
    research_path: str | Path,
    site_path: str | Path,
):
    """Build the FastAPI app. ``supabase`` is any object with select/upsert/replace."""
    people_path = Path(people_path)
    research_path = Path(research_path)
    site_path = Path(site_path)

    app = FastAPI(title="HCT data viewer")
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "viewer_templates"))
    templates.env.filters["cell"] = _cell

    def _render(request, name, ctx, status_code=200):
        return templates.TemplateResponse(request, name, ctx, status_code=status_code)

    def _rows(table: str) -> list[dict[str, Any]]:
        return supabase.select(table)

    def _find(table: str, pk_value: str) -> dict[str, Any] | None:
        pk = TABLE_SPEC[table]["pk"]
        return next((r for r in _rows(table) if str(r.get(pk)) == str(pk_value)), None)

    def _redirect(request, table, msg):
        url = request.url_for("table_view", table=table).include_query_params(msg=msg)
        return RedirectResponse(str(url), status_code=303)

    # -- read --------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    async def overview(request: Request):
        tables = []
        for name in TABLE_SPEC:
            try:
                count: Any = len(_rows(name))
            except Exception as exc:  # surface a dead connection instead of 500
                count = f"error: {exc}"
            tables.append({"name": name, "count": count})
        return _render(request, "overview.html", {"tables": tables, "spec": TABLE_SPEC})

    @app.get("/t/{table}", response_class=HTMLResponse)
    async def table_view(request: Request, table: str):
        spec = TABLE_SPEC.get(table)
        if not spec:
            raise HTTPException(status_code=404)
        rows = _rows(table)
        return _render(
            request, "table.html",
            {"table": table, "spec": spec, "rows": rows, "columns": spec["columns"]},
        )

    # -- edit --------------------------------------------------------------
    def _form_fields(spec: dict, row: dict | None) -> list[dict]:
        fields = []
        for col in spec["editable"]:
            raw = (row or {}).get(col)
            if col in spec["json"]:
                value = json.dumps(raw or {}, indent=2, ensure_ascii=False)
            else:
                value = "" if raw is None else str(raw)
            fields.append({
                "name": col,
                "value": value,
                "textarea": col in TEXTAREA_FIELDS or col in spec["json"],
            })
        return fields

    def _error_fields(spec: dict, form) -> list[dict]:
        return [
            {"name": c, "value": form.get(c, ""),
             "textarea": c in TEXTAREA_FIELDS or c in spec["json"]}
            for c in spec["editable"]
        ]

    @app.get("/t/{table}/edit", response_class=HTMLResponse)
    async def edit_form(request: Request, table: str, id: str = ""):
        spec = TABLE_SPEC.get(table)
        if not spec:
            raise HTTPException(status_code=404)
        row = _find(table, id)
        if row is None:
            raise HTTPException(status_code=404)
        return _render(
            request, "edit.html",
            {"table": table, "spec": spec, "pk_value": id,
             "fields": _form_fields(spec, row), "error": None},
        )

    @app.post("/t/{table}/edit", response_class=HTMLResponse)
    async def edit_apply(request: Request, table: str, id: str = ""):
        spec = TABLE_SPEC.get(table)
        if not spec:
            raise HTTPException(status_code=404)
        form = await request.form()
        try:
            if spec["edit"] == "supabase":
                _apply_supabase_edit(table, spec, id, form)
            else:
                _apply_yaml_edit(table, id, form)
        except (ValueError, ContentError, SiteContentError) as exc:
            return _render(
                request, "edit.html",
                {"table": table, "spec": spec, "pk_value": id,
                 "fields": _error_fields(spec, form), "error": str(exc)},
                status_code=400,
            )
        return _redirect(request, table, f"Saved {table}: {id}")

    # -- add / delete (yaml tables only) -----------------------------------
    @app.get("/t/{table}/add", response_class=HTMLResponse)
    async def add_form(request: Request, table: str):
        spec = TABLE_SPEC.get(table)
        if not spec or not spec.get("addable"):
            raise HTTPException(status_code=404)
        return _render(
            request, "add.html",
            {"table": table, "spec": spec,
             "fields": [{"name": c, "value": "", "textarea": c in TEXTAREA_FIELDS}
                        for c in spec["editable"]], "error": None},
        )

    @app.post("/t/{table}/add", response_class=HTMLResponse)
    async def add_apply(request: Request, table: str):
        spec = TABLE_SPEC.get(table)
        if not spec or not spec.get("addable"):
            raise HTTPException(status_code=404)
        form = await request.form()
        try:
            _apply_yaml_add(table, form)
        except (ValueError, ContentError) as exc:
            return _render(
                request, "add.html",
                {"table": table, "spec": spec,
                 "fields": [{"name": c, "value": form.get(c, ""),
                             "textarea": c in TEXTAREA_FIELDS} for c in spec["editable"]],
                 "error": str(exc)},
                status_code=400,
            )
        return _redirect(request, table, f"Added {table}: {form.get(spec['pk'], '')}")

    @app.post("/t/{table}/delete")
    async def delete_apply(request: Request, table: str, id: str = ""):
        spec = TABLE_SPEC.get(table)
        if not spec or not spec.get("addable"):
            raise HTTPException(status_code=404)
        _apply_yaml_delete(table, id)
        return _redirect(request, table, f"Deleted {table}: {id}")

    # -- write helpers -----------------------------------------------------
    def _apply_supabase_edit(table, spec, pk_value, form):
        row = _find(table, pk_value)
        if row is None:
            raise ValueError(f"no {table} row with {spec['pk']}={pk_value!r}")
        updated = dict(row)
        for col in spec["editable"]:
            if col in form:
                updated[col] = _clean(form[col])
        # Validate through the Pydantic contract before writing (e.g. link URL).
        if table == "publications":
            Publication.model_validate({**updated, "id": updated.get("slug")})
        elif table == "timeline":
            TimelineEntry.model_validate(updated)
        supabase.upsert(table, [updated], on_conflict=spec["pk"])

    def _resync_people_research():
        """Bulk-resync people/research from their (just-rewritten) YAML files.

        This alone is NOT how an explicit edit/add/delete below reaches
        Supabase (see the direct _push_yaml_* calls) -- it runs *afterward*,
        purely to propagate side effects of the YAML rewrite that a single-row
        push doesn't cover, namely other rows' ``sort_order`` shifting when an
        item is inserted/removed from the middle of the list. It's always
        safe to also run: the bulk sync's insert/delete/fill-if-empty diff
        (see ``sync_content._bulk_sync``) is idempotent against a row that was
        just pushed directly -- the fill-if-empty PATCH server-side ``is.null``
        filter simply no-ops once the direct push already set that field.
        """
        sync_mod.sync_content(people_path, research_path, supabase=supabase)

    def _row_key(table: str, item) -> tuple[str, str]:
        """(key column, key value) Supabase actually keys this table by --
        see :data:`_KEY_COLUMN`. The value is derived from the item (research's
        slug follows the title, so it can change under an edit)."""
        if table == "people":
            return _KEY_COLUMN[table], item.name
        return _KEY_COLUMN[table], item.with_slug().slug

    def _push_yaml_edit(table, old_item, new_item) -> None:
        """Force this one row's new values straight into Supabase -- an
        explicit maintainer edit must always take effect, independent of the
        bulk sync's fill-if-empty rule for automated re-syncs.

        Only the columns this form owns are sent (:func:`_push_columns`): a
        full row would carry the fields the form never asked about as nulls
        and wipe them."""
        key, old_key_val = _row_key(table, old_item)
        _, new_key_val = _row_key(table, new_item)
        if old_key_val != new_key_val:
            # Identity changed (e.g. a research title edit changes its
            # derived slug) -- this is really a rename: drop the stale row.
            supabase.delete(table, params={key: f"eq.{old_key_val}"})
        supabase.upsert(table, [_push_payload(table, new_item)], on_conflict=key)

    def _push_yaml_add(table, item) -> None:
        # Same narrowed shape as the edit push: the columns the form doesn't
        # own are simply absent, so the DB's own defaults (null) apply rather
        # than this write asserting a value for them.
        supabase.insert(table, [_push_payload(table, item)])

    def _push_yaml_delete(table, item) -> None:
        """Force-remove this one row -- an explicit delete must always take
        effect, not depend on a subsequent bulk resync noticing it's gone."""
        key, key_val = _row_key(table, item)
        supabase.delete(table, params={key: f"eq.{key_val}"})

    def _apply_yaml_edit(table, pk_value, form):
        if table == "site_content":
            return _apply_site_edit(pk_value, form)
        items, path, pkattr = _yaml_items(table)
        idx = _index_of(items, pkattr, pk_value)
        if idx is None:
            raise ValueError(f"no {table} row with {pkattr}={pk_value!r}")
        old_item = items[idx]
        new_item = _build_item(table, form, sort_order=idx)
        items[idx] = new_item
        _reindex(items)
        _dump(table, path, items)
        _push_yaml_edit(table, old_item, new_item)
        _resync_people_research()

    def _apply_yaml_add(table, form):
        items, path, pkattr = _yaml_items(table)
        new = _build_item(table, form, sort_order=len(items))
        if _index_of(items, pkattr, getattr(new, pkattr)) is not None:
            raise ValueError(f"{table} already has {pkattr}={getattr(new, pkattr)!r}")
        items.append(new)
        _reindex(items)
        _dump(table, path, items)
        _push_yaml_add(table, new)
        _resync_people_research()

    def _apply_yaml_delete(table, pk_value):
        items, path, pkattr = _yaml_items(table)
        idx = _index_of(items, pkattr, pk_value)
        old_item = items[idx] if idx is not None else None
        kept = [it for it in items if str(getattr(it, pkattr)) != str(pk_value)]
        _reindex(kept)
        _dump(table, path, kept)
        if old_item is not None:
            _push_yaml_delete(table, old_item)
        _resync_people_research()

    def _apply_site_edit(pk_value, form):
        contents = load_site_yaml(site_path)
        idx = next((i for i, c in enumerate(contents) if c.key == pk_value), None)
        if idx is None:
            raise ValueError(f"no site_content row with key={pk_value!r}")
        try:
            value = json.loads(form.get("value", ""))
        except json.JSONDecodeError as exc:
            raise ValueError(f"value is not valid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("value must be a JSON object")
        contents[idx] = SiteContent(key=pk_value, value=value)
        dump_site_yaml(site_path, contents)
        rows = [c.row() for c in load_site_yaml(site_path)]  # re-validate
        supabase.upsert("site_content", rows, on_conflict="key")

    # -- yaml item plumbing ------------------------------------------------
    def _yaml_items(table):
        if table == "people":
            return load_people_yaml(people_path), people_path, "name"
        if table == "research":
            return load_research_yaml(research_path), research_path, "title"
        raise ValueError(f"{table} is not a YAML-backed table")

    def _dump(table, path, items):
        if table == "people":
            dump_people_yaml(path, items)
        else:
            dump_research_yaml(path, items)

    return app


def _index_of(items, attr, pk_value):
    for i, it in enumerate(items):
        if str(getattr(it, attr)) == str(pk_value):
            return i
    return None


def _reindex(items) -> None:
    for i, it in enumerate(items):
        it.sort_order = i


def _build_item(table: str, form: Any, *, sort_order: int):
    """Construct a validated Person/ResearchProject from form fields."""
    status = (form.get("kind") or "current").strip().lower()
    if table == "people":
        if status not in _PEOPLE_KINDS:
            raise ValueError(f"status {status!r} must be one of {sorted(_PEOPLE_KINDS)}")
        name = _clean(form.get("name"))
        if not name:
            raise ValueError("name is required")
        return Person(
            name=name, role=_clean(form.get("role")), email=_clean(form.get("email")),
            photo=_clean(form.get("photo")), kind=status, sort_order=sort_order,
        )
    if table == "research":
        if status not in _RESEARCH_KINDS:
            raise ValueError(f"status {status!r} must be one of {sorted(_RESEARCH_KINDS)}")
        title = _clean(form.get("title"))
        if not title:
            raise ValueError("title is required")
        return ResearchProject(
            title=title, tagline=_clean(form.get("tagline")), link=_clean(form.get("link")),
            image=_clean(form.get("image")), kind=status, sort_order=sort_order,
        )
    raise ValueError(f"{table} is not a YAML-backed table")
