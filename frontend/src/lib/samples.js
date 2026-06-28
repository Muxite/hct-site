export const STYLE_ORDER = ["A", "B", "C", "D", "E"];

export const STYLE_NAMES = {
  A: "Plain-language explainer",
  B: "Technical abstract",
  C: "Problem / Approach / Result",
  D: "Significance-first",
  E: "Question and answer",
};

/**
 * Group flat paper_samples rows into a paper -> style -> mode tree.
 *
 * :param rows: paper_samples rows from Supabase.
 * :returns: papers ordered by their lowest position.
 */
export function groupSamples(rows) {
  const allowed = new Set(STYLE_ORDER);
  const byPaper = new Map();
  for (const r of rows || []) {
    if (!allowed.has(r.style)) continue;
    if (!byPaper.has(r.paper_slug)) {
      byPaper.set(r.paper_slug, {
        slug: r.paper_slug,
        link: r.link,
        oa_url: r.oa_url,
        confidence: r.confidence,
        minPos: r.position ?? 0,
        styleMap: new Map(),
      });
    }
    const p = byPaper.get(r.paper_slug);
    p.minPos = Math.min(p.minPos, r.position ?? 0);
    if (p.link == null) p.link = r.link;
    if (p.oa_url == null) p.oa_url = r.oa_url;
    if (p.confidence == null) p.confidence = r.confidence;
    if (!p.styleMap.has(r.style)) p.styleMap.set(r.style, { style: r.style, modes: {} });
    p.styleMap.get(r.style).modes[r.mode] = r;
  }
  return [...byPaper.values()]
    .sort((a, z) => a.minPos - z.minPos)
    .map((p) => ({
      slug: p.slug,
      link: p.link,
      oa_url: p.oa_url,
      confidence: p.confidence,
      styles: [...p.styleMap.values()].sort(
        (a, z) => STYLE_ORDER.indexOf(a.style) - STYLE_ORDER.indexOf(z.style),
      ),
    }));
}

/**
 * Build lightweight browser-side quality checks for a generated paragraph.
 *
 * :param text: generated summary text.
 * :returns: word count and readable pass/fail checks.
 */
export function sampleQuality(text) {
  const value = text || "";
  const words = (value.match(/\b[\w'-]+\b/g) || []).length;
  const hasDash = /[—–]/.test(value);
  const hasEmoji = /[\u{1f000}-\u{1faff}\u{2600}-\u{27bf}\u{2b00}-\u{2bff}]/u.test(value);
  const fillerOpening = /^(this paper|in this paper|this study|this work|the paper)\b/i.test(
    value.trim(),
  );
  return {
    words,
    checks: [
      words >= 12 && words <= 140 ? "good length" : "length needs review",
      hasDash ? "dash needs review" : "no em/en dash",
      hasEmoji ? "emoji needs review" : "no emoji",
      fillerOpening ? "generic opener" : "direct opener",
    ],
  };
}
