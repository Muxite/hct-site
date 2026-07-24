/**
 * Cut a Markdown-subset site_content block into an intro plus heading-titled
 * sections. `sponsors` and `opportunities` are authored as an optional lead
 * paragraph followed by "###" groups (Industry / Government / University;
 * Undergraduate / PhD / RA / Post-Doc / Visiting), and the modern looks render
 * those groups as separate units — a collapsible panel each, or a titled block.
 *
 * The split level is whatever the *first* heading uses, so this works whether
 * the content is authored with "##" or "###". A deeper heading is left in place
 * as an ordinary block inside its parent section.
 *
 * Each section carries both its parsed `blocks` and its raw markdown `text`.
 * <Prose> takes a string, so returning the slice here keeps heading-scanning in
 * one tested place instead of re-deriving it inside a component.
 *
 * Pure (no React/DOM) so it is unit-testable.
 */
import { parseMarkdown } from "./prose.js";

// The same heading shape parseMarkdown recognizes — the line scan below and the
// block list must agree on what counts as a heading or the slices would drift.
const HEADING_LINE = /^\s*(#{1,4})\s+(.+?)\s*$/;

/** Flatten an inline node array to plain text (drops bold/link markup). */
export function inlineText(nodes) {
  return (nodes || [])
    .map((n) => {
      if (n.t === "text") return n.v;
      if (n.t === "break") return " ";
      if (n.t === "bold" || n.t === "link") return inlineText(n.children);
      return "";
    })
    .join("")
    .replace(/\s+/g, " ")
    .trim();
}

export function splitSections(text) {
  const src = String(text ?? "").replace(/\r/g, "");
  const blocks = parseMarkdown(src);
  const first = blocks.find((b) => b.type === "heading");
  if (!first) return { intro: blocks, introText: src.trim(), sections: [] };

  const level = first.level;
  const lines = src.split("\n");
  const slice = (from, to) => lines.slice(from, to).join("\n").trim();
  // Where each split-level heading starts, so a section's raw text is the span
  // between its heading line and the next one.
  const cuts = [];
  lines.forEach((line, i) => {
    const m = HEADING_LINE.exec(line);
    if (m && m[1].length <= level) cuts.push(i);
  });

  const intro = [];
  const sections = [];
  for (const b of blocks) {
    if (b.type === "heading" && b.level <= level) {
      sections.push({ title: inlineText(b.inline), blocks: [], text: "" });
      continue;
    }
    (sections.length ? sections[sections.length - 1].blocks : intro).push(b);
  }
  // cuts and sections are produced by the same predicate, so they align 1:1.
  sections.forEach((s, i) => {
    s.text = slice(cuts[i] + 1, i + 1 < cuts.length ? cuts[i + 1] : lines.length);
  });

  return { intro, introText: slice(0, cuts[0]), sections };
}
