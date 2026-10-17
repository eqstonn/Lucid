/* Brightspace content script.
 *
 * Two scrapers, chosen by URL when the side panel (via background.js) sends {type: "lucid:scrape-page"}:
 *   - Syllabus Hunter: finds the syllabus PDF on a course content/lessons page and returns its bytes.
 *   - Grade Scraper:   reads the "My Grades" table and returns [{name, score, max}].
 * Due dates are deliberately ignored.
 *
 * Brightspace markup is deeply nested and varies by institution/theme, so everything that touches
 * the DOM or URL shapes lives in CONFIG below. Tune CONFIG first when a page stops scraping.
 */
(() => {
  const CONFIG = {
    pages: {
      grades: /\/d2l\/lms\/grades\//i,
      content: /\/d2l\/le\/(?:lessons|content)\//i,
    },
    // First capture group is the course org-unit id.
    orgId: [/[?&]ou=(\d+)/i, /\/d2l\/(?:le\/(?:lessons|content)|home|lms\/grades\/my_grades\/main\.d2l\/?)\/(\d+)/i],
    courseName: {
      selectors: [
        "d2l-navigation-main-footer a.d2l-navigation-s-link[href*='/d2l/home/']",
        "a.d2l-navigation-s-link[href*='/d2l/home/']",
        ".d2l-navigation-s-course-menu .d2l-navigation-s-link",
        "d2l-navigation-s-course-title",
        "h1.d2l-page-title",
      ],
      // Used on document.title when no selector hits: "Grades - COMP 1805 A - Fall 2026" -> "COMP 1805 A - Fall 2026".
      titlePrefix: /^\s*(?:my\s+)?(?:grades|content|lessons|course\s+content)\s*[-–|:]\s*/i,
    },
    grades: {
      tables: ["table", "[role='table']", "[role='grid']"],
      rows: ["tr", "[role='row']"],
      cells: ["th", "td", "[role='rowheader']", "[role='gridcell']", "[role='cell']"],
      nameCells: ["th", "[role='rowheader']", "td:first-child"],
    },
    syllabus: {
      // Where to look for candidate URLs: [css selector, attribute].
      sources: [
        ["iframe[src]", "src"],
        ["embed[src]", "src"],
        ["object[data]", "data"],
        ["d2l-pdf-viewer[src]", "src"],
        ["a[href]", "href"],
      ],
      urlPatterns: [/\.pdf(?:[?#]|$)/i, /DirectFileTopicDownload/i, /\/content\/enforced\//i, /\/viewFile\b/i],
      // Viewer wrappers like viewer.html?file=<real url>.
      unwrapParams: ["file", "src", "url"],
      preferred: /outline|syllabus|syllabi/i,
      external: /(?:docs|drive)\.google\.com|onedrive\.live\.com|sharepoint\.com/i,
      maxBytes: 25 * 1024 * 1024,
      maxCandidatesTried: 6,
    },
  };

  // ---- pure helpers (unit-tested in content.test.js) -----------------------

  const SCORE_RE = /(-|–|—|\d+(?:[.,]\d+)?)\s*\/\s*(\d+(?:[.,]\d+)?)/;

  /** "5.5 / 5.5" -> {score: 5.5, max: 5.5}; "- / 10" -> {score: null, max: 10}; no match -> null. */
  function parseScore(text) {
    const m = SCORE_RE.exec(String(text || "").replace(/\s+/g, " "));
    if (!m) return null;
    const num = (s) => Number(s.replace(",", "."));
    const max = num(m[2]);
    if (!(max > 0)) return null;
    return { score: /^\d/.test(m[1]) ? num(m[1]) : null, max };
  }

  function firstMatch(patterns, text) {
    for (const re of patterns) {
      const m = re.exec(text);
      if (m) return m[1];
    }
    return null;
  }

  function resolveUrl(raw, base) {
    try { return new URL(raw, base); } catch (_) { return null; }
  }

  /** Raw attribute values -> ranked absolute PDF candidate URLs, plus any external-doc links. */
  function classifyUrls(rawUrls, base, cfg = CONFIG.syllabus) {
    const pdfs = [];
    const external = [];
    const seen = new Set();
    for (const raw of rawUrls) {
      let url = resolveUrl(raw, base);
      if (!url || !/^https?:$/.test(url.protocol)) continue;
      for (const p of cfg.unwrapParams) {
        const inner = url.searchParams.get(p);
        if (inner && cfg.urlPatterns.some((re) => re.test(inner))) {
          url = resolveUrl(inner, url) || url;
          break;
        }
      }
      const href = url.href;
      if (seen.has(href)) continue;
      seen.add(href);
      if (cfg.urlPatterns.some((re) => re.test(href))) pdfs.push(href);
      else if (cfg.external.test(url.hostname)) external.push(href);
    }
    const rank = (u) => (cfg.preferred.test(decodeURIComponent(u)) ? 0 : 1);
    pdfs.sort((a, b) => rank(a) - rank(b));
    return { pdfs, external };
  }

  function bytesToBase64(bytes) {
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(bin);
  }

  function isPdf(bytes) {
    const head = new TextDecoder("latin1").decode(bytes.subarray(0, 1024));
    return head.includes("%PDF-");
  }

  // ---- DOM helpers ---------------------------------------------------------

  /** querySelectorAll that also walks open shadow roots and same-origin iframes. */
  function deepQueryAll(root, selector, out = []) {
    root.querySelectorAll(selector).forEach((el) => out.push(el));
    const all = root.querySelectorAll("*");
    for (const el of all) {
      if (el.shadowRoot) deepQueryAll(el.shadowRoot, selector, out);
      if (el.tagName === "IFRAME") {
        try {
          if (el.contentDocument) deepQueryAll(el.contentDocument, selector, out);
        } catch (_) { /* cross-origin frame */ }
      }
    }
    return out;
  }

  const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const cellText = (el) => clean(el.innerText || el.textContent);
  const firstLine = (el) => {
    const lines = String(el.innerText || el.textContent || "").split(/\n+/).map(clean).filter(Boolean);
    return lines[0] || "";
  };

  function getOrgId(url) {
    return firstMatch(CONFIG.orgId, url);
  }

  function getCourseName() {
    for (const sel of CONFIG.courseName.selectors) {
      const el = deepQueryAll(document, sel)[0];
      const text = el && cellText(el);
      if (text) return text;
    }
    const title = clean(document.title).replace(CONFIG.courseName.titlePrefix, "");
    return title || null;
  }

  // ---- Grade Scraper -------------------------------------------------------

  function scrapeGrades() {
    const g = CONFIG.grades;
    const found = [];
    const seen = new Set();
    for (const table of deepQueryAll(document, g.tables.join(","))) {
      for (const row of table.querySelectorAll(g.rows.join(","))) {
        const cells = Array.from(row.querySelectorAll(g.cells.join(",")));
        if (cells.length < 2) continue;
        const nameCell = row.querySelector(g.nameCells.join(",")) || cells[0];
        const name = firstLine(nameCell);
        if (!name) continue;
        let parsed = null;
        for (const c of cells) {
          if (c === nameCell) continue;
          parsed = parseScore(cellText(c));
          if (parsed) break;
        }
        if (!parsed) continue;
        const key = name + "|" + parsed.score + "|" + parsed.max;
        if (seen.has(key)) continue;
        seen.add(key);
        found.push({ name, score: parsed.score, max: parsed.max });
      }
    }
    return found;
  }

  // ---- Syllabus Hunter -----------------------------------------------------

  async function fetchPdf(url) {
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const bytes = new Uint8Array(await res.arrayBuffer());
    if (bytes.length > CONFIG.syllabus.maxBytes) throw new Error("PDF too large");
    if (!isPdf(bytes)) throw new Error("not a PDF");
    return bytes;
  }

  async function huntSyllabus() {
    const cfg = CONFIG.syllabus;
    const raw = [];
    for (const [sel, attr] of cfg.sources) {
      for (const el of deepQueryAll(document, sel)) {
        const v = el.getAttribute(attr);
        if (v) raw.push(v);
      }
    }
    const { pdfs, external } = classifyUrls(raw, location.href);
    for (const url of pdfs.slice(0, cfg.maxCandidatesTried)) {
      try {
        const bytes = await fetchPdf(url);
        const last = decodeURIComponent(new URL(url).pathname.split("/").pop() || "");
        return { pdf: { base64: bytesToBase64(bytes), url, filename: /\.pdf$/i.test(last) ? last : "syllabus.pdf" }, external: null };
      } catch (_) { /* try the next candidate */ }
    }
    return { pdf: null, external: external[0] || null };
  }

  // ---- entry ---------------------------------------------------------------

  async function scrapePage() {
    const url = location.href;
    const base = { ok: true, orgId: getOrgId(url), courseName: getCourseName() };
    if (CONFIG.pages.grades.test(url)) return { ...base, kind: "grades", grades: scrapeGrades() };
    if (CONFIG.pages.content.test(url)) return { ...base, kind: "content", ...(await huntSyllabus()) };
    return { ...base, kind: "other" };
  }

  const api = { CONFIG, parseScore, classifyUrls, bytesToBase64, isPdf, getOrgId };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else if (typeof chrome !== "undefined" && chrome.runtime && !window.__lucidContent) {
    window.__lucidContent = true; // guard against double injection (manifest + scripting.executeScript)
    chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
      if (!msg || msg.type !== "lucid:scrape-page") return false;
      scrapePage().then(sendResponse, (err) => sendResponse({ ok: false, error: String(err && err.message || err) }));
      return true; // async response
    });
  }
})();
