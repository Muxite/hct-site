/**
 * Small Markdown subset parser for the site_content prose blocks. The original
 * HCT site rendered structured content (headings, ordered/unordered lists,
 * bold, inline links); that structure is authored as Markdown in the backend
 * site.yaml and reproduced here. Pure (no React/DOM) so it is unit-testable.
 *
 * Supported:
 *   - "## " / "### " headings
 *   - "- " / "* " unordered and "1." ordered lists, one level of nesting
 *   - paragraphs (soft-wrapped: single newlines flow as spaces; a line ending
 *     in two spaces or "\" forces a hard break)
 *   - inline **bold**, [label](href), bare URLs, and "user [at] domain" emails
 */

const LINK_RE = /\[([^\]]+)\]\((https?:\/\/[^\s)]+|mailto:[^\s)]+)\)/;
const URL_RE = /https?:\/\/[^\s<)]+[^\s<).,;:]/;
const EMAIL_RE = /[A-Za-z0-9._%+-]+\s*[[(]at[\])]\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}/;
const BOLD_RE = /\*\*([^*]+)\*\*/;

/** Parse inline text into text / bold / link nodes. */
export function parseInline(text) {
  const nodes = [];
  let s = String(text ?? "");
  while (s.length) {
    const cands = [];
    let m;
    if ((m = LINK_RE.exec(s)))
      cands.push({ i: m.index, len: m[0].length, make: (mm) => ({ t: "link", href: mm[2], children: parseInline(mm[1]) }), m });
    if ((m = BOLD_RE.exec(s)))
      cands.push({ i: m.index, len: m[0].length, make: (mm) => ({ t: "bold", children: parseInline(mm[1]) }), m });
    if ((m = URL_RE.exec(s)))
      cands.push({ i: m.index, len: m[0].length, make: (mm) => ({ t: "link", href: mm[0], children: [{ t: "text", v: mm[0] }] }), m });
    if ((m = EMAIL_RE.exec(s)))
      cands.push({ i: m.index, len: m[0].length, make: (mm) => ({ t: "link", href: "mailto:" + mm[0].replace(/\s*[[(]at[\])]\s*/, "@"), children: [{ t: "text", v: mm[0] }] }), m });
    if (!cands.length) {
      nodes.push({ t: "text", v: s });
      break;
    }
    // earliest match wins; on a tie prefer the longest (markdown link over bare URL)
    cands.sort((a, b) => a.i - b.i || b.len - a.len);
    const c = cands[0];
    if (c.i > 0) nodes.push({ t: "text", v: s.slice(0, c.i) });
    nodes.push(c.make(c.m));
    s = s.slice(c.i + c.len);
  }
  return nodes;
}

const indentOf = (raw) => (/^(\s*)/.exec(raw)[1] || "").replace(/\t/g, "  ").length;
const isListLine = (raw) => /^\s*(?:[-*+]|\d+\.)\s+\S/.test(raw);
const isBlank = (raw) => raw.trim() === "";

function parseItemLine(raw) {
  const m = /^\s*(?:([-*+])|(\d+)\.)\s+(.*)$/.exec(raw);
  return { ordered: m[2] !== undefined, text: m[3] };
}

// Parse a list starting at `start` whose items sit at column `baseIndent`.
// Returns [listBlock, nextLineIndex].
function parseList(lines, start, baseIndent) {
  const ordered = parseItemLine(lines[start]).ordered;
  const items = [];
  let i = start;
  while (i < lines.length) {
    const raw = lines[i];
    if (isBlank(raw)) {
      let j = i + 1;
      while (j < lines.length && isBlank(lines[j])) j++;
      if (j < lines.length && isListLine(lines[j]) && indentOf(lines[j]) >= baseIndent) {
        i = j;
        continue;
      }
      break;
    }
    if (!isListLine(raw)) break;
    const ind = indentOf(raw);
    if (ind < baseIndent) break;
    if (ind > baseIndent) {
      const [sub, ni] = parseList(lines, i, ind);
      if (items.length) items[items.length - 1].list = sub;
      i = ni;
      continue;
    }
    items.push({ inline: parseInline(parseItemLine(raw).text) });
    i++;
  }
  return [{ type: "list", ordered, items }, i];
}

/** Parse a Markdown-subset string into a flat array of blocks. */
export function parseMarkdown(text) {
  const lines = String(text ?? "").replace(/\r/g, "").split("\n");
  const blocks = [];
  let para = [];

  const flush = () => {
    if (!para.length) return;
    const inline = [];
    para.forEach((raw, idx) => {
      if (idx > 0) inline.push(para[idx - 1].hard ? { t: "break" } : { t: "text", v: " " });
      inline.push(...parseInline(raw.text));
    });
    blocks.push({ type: "paragraph", inline });
    para = [];
  };

  let i = 0;
  while (i < lines.length) {
    const raw = lines[i];
    if (isBlank(raw)) {
      flush();
      i++;
      continue;
    }
    const h = /^\s*(#{1,4})\s+(.+?)\s*$/.exec(raw);
    if (h) {
      flush();
      blocks.push({ type: "heading", level: h[1].length, inline: parseInline(h[2]) });
      i++;
      continue;
    }
    if (isListLine(raw)) {
      flush();
      const [list, ni] = parseList(lines, i, indentOf(raw));
      blocks.push(list);
      i = ni;
      continue;
    }
    para.push({ text: raw.trim().replace(/\\$/, ""), hard: /\s{2,}$/.test(raw) || /\\$/.test(raw.trim()) });
    i++;
  }
  flush();
  return blocks;
}
