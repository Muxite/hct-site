import { parseMarkdown } from "../lib/prose.js";

// Renders a Markdown-subset site_content block the way the original site did:
// headings, ordered/unordered lists (one level of nesting), bold, and links
// (markdown links, bare URLs, and "user [at] domain" emails).
export default function Prose({ text }) {
  const blocks = parseMarkdown(text);
  if (!blocks.length) return null;
  return <div className="prose">{blocks.map((b, i) => renderBlock(b, i))}</div>;
}

function renderBlock(block, key) {
  if (block.type === "heading") {
    const Tag = `h${Math.min(block.level + 2, 6)}`; // "##" -> h4, "###" -> h5
    return (
      <Tag key={key} className="prose__heading">
        <i>{renderInline(block.inline)}</i>
      </Tag>
    );
  }
  if (block.type === "list") return renderList(block, key);
  return <p key={key}>{renderInline(block.inline)}</p>;
}

function renderList(list, key) {
  const Tag = list.ordered ? "ol" : "ul";
  return (
    <Tag key={key}>
      {list.items.map((it, i) => (
        <li key={i}>
          {renderInline(it.inline)}
          {it.list && renderList(it.list, `${i}-sub`)}
        </li>
      ))}
    </Tag>
  );
}

function renderInline(nodes) {
  return (nodes || []).map((n, i) => {
    if (n.t === "text") return n.v;
    if (n.t === "break") return <br key={i} />;
    if (n.t === "bold") return <strong key={i}>{renderInline(n.children)}</strong>;
    if (n.t === "link") {
      const external = !n.href.startsWith("mailto:");
      return (
        <a
          key={i}
          href={n.href}
          target={external ? "_blank" : undefined}
          rel={external ? "noopener noreferrer" : undefined}
        >
          {renderInline(n.children)}
        </a>
      );
    }
    return null;
  });
}
