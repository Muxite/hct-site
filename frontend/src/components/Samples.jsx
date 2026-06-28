import Prose from "./Prose.jsx";
import { groupSamples, sampleQuality, STYLE_NAMES } from "../lib/samples.js";

const PRIMARY_MODE = "rag";

export default function Samples({ samples, publications }) {
  const papers = groupSamples(samples);
  const pubBySlug = Object.fromEntries((publications || []).map((p) => [p.slug, p]));

  return (
    <section className="samples">
      <p className="samples__back">
        <a href="/">Back to main site</a>
      </p>
      <h2>Paper page style options</h2>
      <p className="samples__intro">
        Three research papers selected by the agent, grounded with retrieval from
        article text, then rewritten as five candidate page paragraphs. Click a
        paper or style to compare tone, structure, and basic quality checks.
      </p>

      {!papers.length && (
        <div className="state">No samples yet — run the paper-summary harness.</div>
      )}

      {!!papers.length && (
        <div className="samples-nav" aria-label="Sample papers and styles">
          {papers.map((paper) => {
            const meta = pubBySlug[paper.slug] || {};
            return (
              <a className="samples-nav__paper" href={`#sample-${paper.slug}`} key={paper.slug}>
                <span>{meta.title || paper.slug}</span>
                <small>{paper.styles.length} styles</small>
              </a>
            );
          })}
        </div>
      )}

      {papers.map((paper) => {
        const meta = pubBySlug[paper.slug] || {};
        return (
          <article className="samples-paper" id={`sample-${paper.slug}`} key={paper.slug}>
            <h3 className="samples-paper__title">{meta.title || paper.slug}</h3>
            <div className="samples-paper__meta">
              {Array.isArray(meta.authors) ? meta.authors.join("; ") : ""}
              {meta.year ? ` · ${meta.year}` : ""}
            </div>
            <div className="samples-paper__links">
              {paper.link && (
                <a href={paper.link} target="_blank" rel="noreferrer">
                  article link
                </a>
              )}
              {paper.oa_url && (
                <>
                  {" · "}
                  <a href={paper.oa_url} target="_blank" rel="noreferrer">
                    open access
                  </a>
                </>
              )}
              {paper.confidence != null && (
                <span className="samples-conf">
                  {" · "}link confidence {Math.round(paper.confidence * 100)}%
                </span>
              )}
            </div>
            <div className="samples-paper__jump">
              {paper.styles.map((st) => (
                <a href={`#sample-${paper.slug}-${st.style}`} key={st.style}>
                  {st.style}. {STYLE_NAMES[st.style]}
                </a>
              ))}
            </div>

            <div className="samples-styles">
              {paper.styles.map((st) => {
                const sample = st.modes[PRIMARY_MODE] || Object.values(st.modes)[0];
                const quality = sampleQuality(sample?.summary);
                return (
                  <div
                    className="samples-style"
                    id={`sample-${paper.slug}-${st.style}`}
                    key={st.style}
                  >
                    <h4 className="samples-style__name">
                      {st.style}. {STYLE_NAMES[st.style] || ""}
                    </h4>
                    <div className="samples-variant">
                      <div className="samples-variant__label">
                        Agent retrieval
                        <span className="samples-variant__cap">
                          {" · "}
                          {sample?.model || "unknown model"}
                          {sample?.completion_tokens
                            ? ` · ${sample.completion_tokens} output tokens`
                            : ""}
                        </span>
                      </div>
                      <Prose text={sample?.summary || "_(no output)_"} />
                      <div className="samples-quality">
                        <span>{quality.words} words</span>
                        {quality.checks.map((check) => (
                          <span key={check}>{check}</span>
                        ))}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </article>
        );
      })}
    </section>
  );
}
