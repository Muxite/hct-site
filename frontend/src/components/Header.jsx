// Original-style masthead: the lab logo beside the title / subtitle / tagline,
// all sourced from the site_meta row in Supabase.
const LOGO = "/Human Communication Technologies Lab_files/logo.png";

export default function Header({ meta }) {
  return (
    <>
      <header>
        <img className="logo" src={LOGO} alt="HCT logo" />
        <div className="column">
          <h1 className="title">{meta.title || "HCT Lab"}</h1>
          {meta.subtitle && <h3 className="subtitle">{meta.subtitle}</h3>}
          {meta.tagline && <div className="optional">{meta.tagline}</div>}
        </div>
      </header>
      <hr />
    </>
  );
}
