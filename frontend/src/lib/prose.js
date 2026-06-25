/**
 * Pure prose parser — ported from the original site's app.js renderer so the
 * dynamic site reproduces the same look. Free text from site_content is split
 * into blocks; short, punctuation-free single lines read as sub-headings (the
 * Sponsors / Opportunities category labels), and URLs + obfuscated
 * "user [at] domain" emails become links. No React, no DOM — unit-testable.
 */

const URL_RE = /https?:\/\/[^\s<]+[^\s<.,)]/g;
const EMAIL_RE = /[A-Za-z0-9._%+-]+\s*[[(]at[\])]\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
// Combined scanner (URL | obfuscated email), used to tokenize a line.
const TOKEN_RE = new RegExp(`(${URL_RE.source})|(${EMAIL_RE.source})`, "g");

// A short, punctuation-free single line reads as a sub-heading.
function isHeading(chunk) {
  return (
    !chunk.includes("\n") &&
    chunk.length <= 55 &&
    !/[.\/,\d]/.test(chunk) &&
    !/[[(]at[\])]/.test(chunk)
  );
}

// Split a single line into text / link nodes.
function tokenizeLine(line) {
  const nodes = [];
  let last = 0;
  for (const m of line.matchAll(TOKEN_RE)) {
    if (m.index > last) nodes.push({ t: "text", v: line.slice(last, m.index) });
    if (m[1]) {
      nodes.push({ t: "link", href: m[1], label: m[1] });
    } else {
      // obfuscated email: "user [at] domain" -> mailto:user@domain
      const addr = m[0].replace(/\s*[[(]at[\])]\s*/, "@");
      nodes.push({ t: "link", href: `mailto:${addr}`, label: m[0] });
    }
    last = m.index + m[0].length;
  }
  if (last < line.length) nodes.push({ t: "text", v: line.slice(last) });
  return nodes;
}

/**
 * Parse free text into renderable blocks:
 *   { type: "heading", text }
 *   { type: "para", lines: [[node, …], …] }   (lines render with <br> between)
 */
export function parseProse(text) {
  return String(text || "")
    .split(/\n\s*\n/)
    .map((c) => c.trim())
    .filter(Boolean)
    .map((chunk) =>
      isHeading(chunk)
        ? { type: "heading", text: chunk }
        : { type: "para", lines: chunk.split("\n").map(tokenizeLine) },
    );
}
