#!/usr/bin/env python3
"""Generate dynamic-site/index.html from the saved static ../hct.html.

The dynamic site keeps the original site's markup/CSS (so it looks identical)
but every data/content section is rendered live from Supabase by app.js:
  * People / Research / Publications  -> the lab's tables (full, current data),
  * the prose sections (Vision, Innovation, Contact, Land Acknowledgment, EDI,
    Sponsors, Opportunities)           -> the site_content key/value store.

This script just prepares the shell: it drops the saved page's local loader
<script>s, restores the Google Font, and empties each section's container so
app.js can fill it. Re-run it whenever ../hct.html changes:

    python3 dynamic-site/build.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "hct.html")
DST = os.path.join(HERE, "index.html")

html = open(SRC, encoding="utf-8").read()
orig_len = len(html)


def sub1(pattern, repl, s, flags=0, label=""):
    s2, n = re.subn(pattern, repl, s, flags=flags)
    if n != 1:
        sys.exit(f"!! expected 1 replacement for {label!r}, got {n}")
    return s2


def empty_section(s, start, end, container_id, label):
    """Replace everything between an <h2> (start) and the next section (end)
    with an empty container app.js will fill."""
    repl = r"\1" + f'\n      <div id="{container_id}"></div>' + r"\2"
    return sub1("(" + start + ").*?(" + end + ")", repl, s, flags=re.S, label=label)


# 1) remove the saved-page local loader scripts (jquery, js-yaml, bibtexParse,
#    yaml.js, bib.js) — app.js renders everything instead.
html, n = re.subn(
    r'\s*<script src="\./Human Communication Technologies Lab_files/[^"]*\.download"></script>',
    "",
    html,
)
print(f"removed {n} local <script> tags")
if n < 3:
    sys.exit("!! expected to remove the local loader scripts")

# 2) restore the real web font (saved copy referenced a local 'css2' file).
html = sub1(
    r'<link href="\./Human Communication Technologies Lab_files/css2" rel="stylesheet">',
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@100;200;300;400;500;600;700;800;900&display=swap" rel="stylesheet">',
    html,
    label="font link",
)

# 3) data sections: empty the wrappers (keep ids; app.js fills them).
html = sub1(
    r'(<div id="people" class="wrapper">).*?(\n\s*<h2>Research</h2>)',
    r"\1</div>\2",
    html,
    flags=re.S,
    label="people wrapper",
)
html = sub1(
    r'(<div id="research" class="wrapper">).*?(\n\s*<div>For past projects)',
    r"\1</div>\2",
    html,
    flags=re.S,
    label="research wrapper",
)

# 4) prose sections: replace each section body with a content container.
prose = [
    (r"<h2>Vision</h2>", r"\n\s*<h2>Innovation</h2>", "vision"),
    (r"<h2>Innovation</h2>", r"\n\s*<h2>People</h2>", "innovation"),
    (r'<h2 class="section">Contact</h2>', r"\n\s*<h2>Land Acknowledgment</h2>", "contact"),
    (r"<h2>Land Acknowledgment</h2>", r"\n\s*<h2>Equity", "land_acknowledgment"),
    (r"<h2>Equity, Diversity, Inclusion \+ Indigeneity</h2>", r"\n\s*<h2>Sponsors</h2>", "edi"),
    (r"<h2>Sponsors</h2>", r"\n\s*<h2>Opportunities</h2>", "sponsors"),
    (r"<h2>Opportunities</h2>", r'\n\s*<h2 id="publications"', "opportunities"),
]
for start, end, key in prose:
    html = empty_section(html, start, end, "content-" + key, "prose:" + key)

# 5) publications: replace the baked-in year-grouped list with one container.
html = sub1(
    r'(<h2 id="publications" class="section">Publications</h2>).*?(\n\s*<br>\s*<footer>)',
    r'\1\n      <div id="publications-list">Loading publications…</div>\2',
    html,
    flags=re.S,
    label="publications block",
)

# 6) inject app.js
html = sub1(r"</body>", '  <script src="./app.js" defer></script>\n</body>', html, label="body close")

open(DST, "w", encoding="utf-8").write(html)
print(f"wrote {DST}: {orig_len} -> {len(html)} bytes")
