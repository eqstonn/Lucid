/* Controller: routing between views, storage, Brightspace scraping, and backend calls. */
(() => {
  const $ = (id) => document.getElementById(id);
  const view = $("view");
  const header = $("header");
  const banner = $("banner");
  let busy = false;
  // Brightspace org-unit id to attach to the next dropzone upload (set when auto-extraction falls back).
  let pendingBrightspaceId = null;

  function setHeader(title) {
    header.replaceChildren(Views.h("span", "text-sm font-semibold tracking-tight text-emerald-400", "Lucid"),
      Views.h("span", "min-w-0 flex-1 truncate text-xs text-neutral-500", title || ""));
  }

  function notify(text, kind) {
    if (!text) { banner.classList.add("hidden"); return; }
    banner.className = "border-b border-neutral-800 px-3 py-1.5 text-xs " +
      (kind === "error" ? "bg-red-950 text-red-300" : "bg-neutral-900 text-neutral-300");
    banner.textContent = text;
  }

  function show(node) {
    view.replaceChildren(node);
    view.scrollTop = 0;
  }

  async function showHome() {
    setHeader("Courses");
    show(Views.home({ courses: await Store.list(), onOpen: showCourse, onAdd: () => showDropzone() }));
  }

  async function showCourse(id) {
    const course = await Store.get(id);
    if (!course) return showHome();
    setHeader(course.name);
    show(Views.courseDetail({
      course,
      onBack: showHome,
      onDelete: async () => { await Store.remove(id); notify(null); showHome(); },
      onEditItem: (ci, ii, patch) => editItem(id, ci, ii, patch),
    }));
  }

  function showDropzone(message, opts) {
    const { name, brightspaceId } = opts || {};
    pendingBrightspaceId = brightspaceId || null;
    setHeader("Add course");
    show(Views.dropzone({
      message,
      defaultName: name,
      onCancel: () => { pendingBrightspaceId = null; showHome(); },
      onFile: addCourseFromPdf,
    }));
  }

  /**
   * Parse a syllabus PDF and store the result. Reuses the course matching `brightspaceId`
   * (keeping any scores already entered); otherwise creates a new one.
   */
  async function importSyllabus(file, name, brightspaceId) {
    const parsed = await Api.parseSyllabus(file);
    const existing = brightspaceId ? (await Store.list()).find((c) => c.brightspaceId === brightspaceId) : null;
    const categories = existing ? Grades.carryScores(existing.categories, parsed) : parsed;
    const standing = await Api.calculateStanding(categories);
    return Store.put({
      id: existing ? existing.id : Store.newId(),
      name: existing ? existing.name : name,
      ...(brightspaceId ? { brightspaceId } : {}),
      categories,
      standing,
    });
  }

  async function addCourseFromPdf(file, name, error) {
    if (error) return notify(error, "error");
    if (!name) return notify("Enter a course name first.", "error");
    if (busy) return;
    busy = true;
    const brightspaceId = pendingBrightspaceId;
    setHeader("Parsing syllabus…");
    show(Views.message("Reading " + file.name + "…"));
    notify(null);
    try {
      const course = await importSyllabus(file, name, brightspaceId);
      pendingBrightspaceId = null;
      busy = false;
      return showCourse(course.id);
    } catch (err) {
      busy = false;
      showDropzone("Extraction failed. Try the PDF again or upload a different file.", { name, brightspaceId });
      notify(err.message, "error");
    }
  }

  async function editItem(courseId, ci, ii, patch) {
    const course = await Store.get(courseId);
    if (!course) return;
    const item = { ...course.categories[ci].items[ii], ...patch };
    if (item.score != null && (item.max_score == null || item.max_score <= 0)) {
      notify("Enter a max score greater than 0 for “" + item.name + "”.", "error");
      return showCourse(courseId);
    }
    if (item.score != null && (!Number.isFinite(item.score) || item.score < 0)) {
      notify("Score must be a non-negative number.", "error");
      return showCourse(courseId);
    }
    course.categories[ci].items[ii] = item;
    try {
      course.standing = await Api.calculateStanding(course.categories);
      await Store.put(course);
      notify(null);
    } catch (err) {
      notify(err.message, "error");
    }
    showCourse(courseId);
  }

  // ---- Brightspace sync ----------------------------------------------------

  function base64ToFile(base64, filename) {
    const bin = atob(base64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new File([bytes], filename, { type: "application/pdf" });
  }

  /** Relay through the service worker to the content script in the active tab. */
  async function scrapeActiveTab() {
    let res;
    try {
      res = await chrome.runtime.sendMessage({ type: "lucid:scrape" });
    } catch (err) {
      throw new Error("Could not reach the extension background worker: " + err.message);
    }
    if (!res) throw new Error("No response from the extension background worker.");
    return res;
  }

  /**
   * Scrape the active Brightspace tab and fold the result into storage.
   * Returns null when the active tab isn't Brightspace, else {message, kind?, next}.
   */
  async function syncFromBrightspace() {
    const res = await scrapeActiveTab();
    if (res.notBrightspace) return null;
    if (!res.ok) throw new Error(res.error);
    const data = res.data;
    const orgId = data.orgId || null;
    const existing = orgId ? (await Store.list()).find((c) => c.brightspaceId === orgId) : null;

    if (data.kind === "grades") {
      if (!existing) {
        throw new Error("No grading scheme for this course yet. Open its syllabus on the Content page and press Sync first.");
      }
      if (!data.grades.length) {
        throw new Error("No grades were found on this page. Selectors may need tuning in content.js.");
      }
      const { categories, matched, unmatched } = Grades.matchGrades(existing.categories, data.grades);
      existing.categories = categories;
      existing.standing = await Api.calculateStanding(categories);
      await Store.put(existing);
      let message = `Grades: matched ${matched} of ${data.grades.filter((g) => g.score != null).length} graded item(s).`;
      if (unmatched.length) message += " Unmatched: " + unmatched.slice(0, 3).join(", ") + (unmatched.length > 3 ? "…" : "");
      return { message, next: () => showCourse(existing.id) };
    }

    if (data.kind === "content") {
      const name = (existing && existing.name) || data.courseName || (orgId ? "Course " + orgId : "New course");
      const fallback = (message) => ({ message, kind: "error", next: () => showDropzone(message, { name, brightspaceId: orgId }) });
      if (!data.pdf) {
        return fallback(data.external
          ? "The syllabus is an external document (" + new URL(data.external).hostname + "). Upload it as a PDF."
          : "No syllabus PDF found on this page. Open the syllabus topic and Sync again, or upload it.");
      }
      setHeader("Parsing syllabus…");
      show(Views.message("Reading " + data.pdf.filename + "…"));
      try {
        const course = await importSyllabus(base64ToFile(data.pdf.base64, data.pdf.filename), name, orgId);
        return { message: "Syllabus imported for " + course.name + ".", next: () => showCourse(course.id) };
      } catch (err) {
        return fallback("Extraction failed: " + err.message);
      }
    }

    return { message: "Open a course's Grades page or its syllabus on the Content page, then Sync.", next: showHome };
  }

  /** Recalculate every cached course (no re-crawl). Used when the active tab isn't Brightspace. */
  async function recalculateAll() {
    const courses = await Store.list();
    for (const c of courses) {
      c.standing = await Api.calculateStanding(c.categories);
      await Store.put(c);
    }
    return courses.length ? "Recalculated " + courses.length + " course(s)." : "Nothing to sync yet.";
  }

  async function sync() {
    if (busy) return;
    busy = true;
    const btn = $("nav-sync");
    btn.disabled = true;
    btn.textContent = "Syncing…";
    let next = showHome;
    try {
      const outcome = await syncFromBrightspace();
      if (outcome) {
        next = outcome.next;
        notify(outcome.message, outcome.kind);
      } else {
        notify(await recalculateAll());
      }
    } catch (err) {
      notify(err.message, "error");
    } finally {
      busy = false;
      btn.disabled = false;
      btn.textContent = "[ Sync ]";
      next();
    }
  }

  $("nav-home").addEventListener("click", () => { notify(null); showHome(); });
  $("nav-sync").addEventListener("click", sync);
  showHome();
})();
