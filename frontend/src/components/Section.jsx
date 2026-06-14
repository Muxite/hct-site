// A titled section with a monospace "eyebrow" index marker. Section.Prose
// renders multi-paragraph free text (splitting on blank lines).
export default function Section({ id, title, eyebrow, children }) {
  return (
    <section className="section" id={id}>
      <div className="section__head">
        {eyebrow && <span className="section__eyebrow">{eyebrow}</span>}
        <h2 className="section__title">{title}</h2>
      </div>
      <div className="section__body">{children}</div>
    </section>
  );
}

Section.Prose = function Prose({ text }) {
  const paragraphs = String(text || "")
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
  return (
    <div className="prose">
      {paragraphs.map((p, i) => (
        <p key={i}>{p}</p>
      ))}
    </div>
  );
};
