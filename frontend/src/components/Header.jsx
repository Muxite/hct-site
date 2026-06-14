// Masthead: lab title, subtitle, tagline, and the nav (all from site_meta).
export default function Header({ meta, nav }) {
  return (
    <header className="masthead">
      <div className="masthead__bar">
        <a className="masthead__mark" href="#top" aria-label="Home">
          HCT
        </a>
        <nav className="masthead__nav">
          {nav.map((label) => (
            <a key={label} href={`#${slugifyNav(label)}`}>
              {label}
            </a>
          ))}
        </nav>
      </div>
      <div className="masthead__hero" id="top">
        <h1 className="masthead__title">{meta.title || "HCT Lab"}</h1>
        {meta.subtitle && <p className="masthead__subtitle">{meta.subtitle}</p>}
        {meta.tagline && <p className="masthead__tagline">{meta.tagline}</p>}
      </div>
    </header>
  );
}

// Map a nav label to the section id used in App ("Latest" -> "latest").
function slugifyNav(label) {
  const map = { Latest: "latest", People: "people", Research: "research" };
  return map[label] || label.toLowerCase();
}
