/* Pure mapping of scraped Brightspace grades onto stored GradingCategory items. No DOM, no chrome.* */
const Grades = (() => {
  const stem = (t) => (t.length > 3 && t.endsWith("s") && !t.endsWith("ss") ? t.slice(0, -1) : t);

  function tokens(name) {
    return String(name)
      .replace(/\([^)]*\)/g, " ") // drop "(20%)"-style annotations
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim()
      .split(" ")
      .filter(Boolean)
      .map(stem);
  }

  /** 0..1 name similarity. Numbered items only ever match items with the same number. */
  function similarity(a, b) {
    const ta = tokens(a);
    const tb = tokens(b);
    if (!ta.length || !tb.length) return 0;
    const na = ta.filter((t) => /^\d+$/.test(t)).join(",");
    const nb = tb.filter((t) => /^\d+$/.test(t)).join(",");
    if (na !== nb) return 0;
    const sa = new Set(ta);
    const sb = new Set(tb);
    let inter = 0;
    sa.forEach((t) => { if (sb.has(t)) inter++; });
    return inter / (sa.size + sb.size - inter);
  }

  const THRESHOLD = 0.5;

  /**
   * Copy `categories`, setting score/max_score on items that best match a scraped grade.
   * scraped: [{name, score: number|null, max: number}]; ungraded rows (score null) are ignored.
   * Returns {categories, matched, unmatched: string[]}.
   */
  function matchGrades(categories, scraped) {
    const out = JSON.parse(JSON.stringify(categories));
    const graded = scraped.filter((g) => g.score != null);
    const pairs = [];
    out.forEach((cat, ci) => cat.items.forEach((item, ii) => {
      graded.forEach((g, gi) => {
        const s = similarity(item.name, g.name);
        if (s >= THRESHOLD) pairs.push({ ci, ii, gi, s });
      });
    }));
    pairs.sort((x, y) => y.s - x.s);

    const usedItems = new Set();
    const usedGrades = new Set();
    let matched = 0;
    for (const p of pairs) {
      const ik = p.ci + ":" + p.ii;
      if (usedItems.has(ik) || usedGrades.has(p.gi)) continue;
      usedItems.add(ik);
      usedGrades.add(p.gi);
      const g = graded[p.gi];
      const item = out[p.ci].items[p.ii];
      item.score = g.score;
      item.max_score = g.max;
      matched++;
    }
    const unmatched = graded.filter((_, gi) => !usedGrades.has(gi)).map((g) => g.name);
    return { categories: out, matched, unmatched };
  }

  /** Re-apply scores from an older category list onto a freshly parsed one (re-import keeps grades). */
  function carryScores(oldCategories, newCategories) {
    const scraped = [];
    for (const cat of oldCategories) {
      for (const it of cat.items) {
        if (it.score != null && it.max_score != null) scraped.push({ name: it.name, score: it.score, max: it.max_score });
      }
    }
    return matchGrades(newCategories, scraped).categories;
  }

  return { similarity, matchGrades, carryScores };
})();

if (typeof module !== "undefined" && module.exports) module.exports = Grades;
