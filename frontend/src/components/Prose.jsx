import { parseProse } from "../lib/prose.js";

// Renders a free-text site_content block the way the original site did: blank
// lines separate blocks, short punctuation-free lines become <h3><i> labels,
// and URLs / "user [at] domain" emails become links.
export default function Prose({ text }) {
  const blocks = parseProse(text);
  if (!blocks.length) return null;
  return (
    <div className="prose">
      {blocks.map((b, i) =>
        b.type === "heading" ? (
          <h3 key={i}>
            <i>{b.text}</i>
          </h3>
        ) : (
          <div key={i}>
            {b.lines.map((nodes, li) => (
              <span key={li}>
                {li > 0 && <br />}
                {nodes.map((n, ni) =>
                  n.t === "link" ? (
                    <a
                      key={ni}
                      href={n.href}
                      target={n.href.startsWith("mailto:") ? undefined : "_blank"}
                      rel="noopener noreferrer"
                    >
                      {n.label}
                    </a>
                  ) : (
                    n.v
                  ),
                )}
              </span>
            ))}
          </div>
        ),
      )}
    </div>
  );
}
