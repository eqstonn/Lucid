/* Pure DOM renderers. They take data + callbacks and return elements; no storage or network here. */
const Views = (() => {
  function h(tag, cls, children, attrs) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (attrs) for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    for (const c of [].concat(children ?? [])) {
      el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  }

  const fmt = (n) => (Number.isInteger(n) ? String(n) : (Math.round(n * 100) / 100).toString());
  const pct = (n) => (n == null ? "—" : fmt(n) + "%");

  function badge(text, extra) {
    return h("span", "shrink-0 rounded border border-neutral-700 bg-neutral-900 px-1.5 py-0.5 font-mono text-xs " + (extra || ""), text);
  }

  function progressBar(standing) {
    const evaluated = Math.min(100, standing.evaluated_weight);
    const earned = Math.min(evaluated, standing.points_earned);
    const track = h("div", "relative h-2 w-full overflow-hidden rounded bg-neutral-800");
    track.append(
      h("div", "absolute inset-y-0 left-0 bg-emerald-900", [], { style: `width:${evaluated}%` }),
      h("div", "absolute inset-y-0 left-0 bg-emerald-400", [], { style: `width:${earned}%` })
    );
    return track;
  }

  function stat(label, value) {
    return h("div", "min-w-0 flex-1", [
      h("div", "text-[10px] uppercase tracking-wide text-neutral-500", label),
      h("div", "truncate font-mono text-sm text-neutral-100", value),
    ]);
  }

  function standingBlock(course) {
    const s = course.standing;
    if (!s) return h("div", "text-xs text-neutral-500", "Standing not calculated yet.");
    return h("div", "space-y-2", [
      h("div", "flex items-center gap-2", [
        h("div", "min-w-0 flex-1", progressBar(s)),
        badge(s.progress_label, "text-emerald-400"),
      ]),
      h("div", "flex gap-3", [stat("Projected", pct(s.projected_grade)), stat("Floor", pct(s.guaranteed_floor))]),
    ]);
  }

  function home({ courses, onOpen, onAdd }) {
    const root = h("div", "space-y-2");
    if (!courses.length) {
      root.append(h("div", "rounded border border-dashed border-neutral-800 p-4 text-center text-xs text-neutral-500",
        "No courses yet. Add one by uploading its syllabus PDF."));
    }
    for (const c of courses) {
      const card = h("button", "block w-full space-y-2 rounded border border-neutral-800 bg-neutral-900 p-3 text-left hover:border-neutral-600");
      card.append(h("div", "truncate font-medium text-neutral-100", c.name), standingBlock(c));
      card.addEventListener("click", () => onOpen(c.id));
      root.append(card);
    }
    const add = h("button", "w-full rounded border border-neutral-800 py-2 text-xs text-neutral-300 hover:bg-neutral-900", "+ Add course");
    add.addEventListener("click", onAdd);
    root.append(add);
    return root;
  }

  /** Editable numeric input that fires onCommit(value|null) on change. */
  function numInput(value, placeholder, onCommit) {
    const input = h("input", "w-12 rounded border border-neutral-700 bg-neutral-950 px-1 py-0.5 text-right font-mono text-xs text-neutral-100 focus:border-emerald-500 focus:outline-none",
      [], { type: "number", min: "0", step: "any", placeholder });
    if (value != null) input.value = value;
    input.addEventListener("change", () => {
      const raw = input.value.trim();
      onCommit(raw === "" ? null : Number(raw));
    });
    return input;
  }

  function courseDetail({ course, onBack, onDelete, onEditItem }) {
    const root = h("div", "space-y-3");
    const back = h("button", "text-xs text-neutral-400 hover:text-neutral-200", "← Courses");
    back.addEventListener("click", onBack);
    root.append(back, h("div", "truncate text-base font-medium text-neutral-100", course.name), standingBlock(course));

    course.categories.forEach((cat, ci) => {
      const section = h("section", "rounded border border-neutral-800");
      section.append(h("div", "flex items-center gap-2 border-b border-neutral-800 bg-neutral-900 px-3 py-1.5", [
        h("span", "min-w-0 flex-1 truncate text-xs font-medium text-neutral-300", cat.name),
        badge(fmt(cat.weight) + "%"),
      ]));
      if (!cat.items.length) section.append(h("div", "px-3 py-2 text-xs text-neutral-500", "No items listed."));
      cat.items.forEach((item, ii) => {
        const row = h("div", "flex items-center gap-2 border-b border-neutral-800 px-3 py-1.5 last:border-b-0");
        row.append(
          h("span", "min-w-0 flex-1 truncate text-xs", [item.name]),
          numInput(item.score, "–", (v) => onEditItem(ci, ii, { score: v })),
          h("span", "text-xs text-neutral-600", "/"),
          numInput(item.max_score, "max", (v) => onEditItem(ci, ii, { max_score: v }))
        );
        row.firstChild.setAttribute("title", item.name + (item.weight != null ? ` (${fmt(item.weight)}%)` : ""));
        section.append(row);
      });
      root.append(section);
    });

    const del = h("button", "w-full rounded border border-red-900 py-2 text-xs text-red-400 hover:bg-red-950", "Remove course");
    del.addEventListener("click", onDelete);
    root.append(del);
    return root;
  }

  /** Upload fallback dropzone; also used to add a new course. */
  function dropzone({ onFile, onCancel, defaultName, message }) {
    const root = h("div", "space-y-3");
    const name = h("input", "w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-xs text-neutral-100 focus:border-emerald-500 focus:outline-none",
      [], { type: "text", placeholder: "Course name (e.g. CS 2310)" });
    if (defaultName) name.value = defaultName;

    const picker = h("input", "hidden", [], { type: "file", accept: "application/pdf,.pdf" });
    const zone = h("div", "cursor-pointer rounded border border-dashed border-neutral-700 p-6 text-center text-xs text-neutral-400 hover:border-emerald-500", [
      h("div", "mb-1 text-neutral-200", "Drop syllabus PDF here"),
      h("div", "", "or click to choose a file"),
    ]);
    const submit = (file) => {
      if (!file) return;
      if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
        onFile(null, name.value.trim(), "Please choose a PDF file.");
        return;
      }
      onFile(file, name.value.trim());
    };
    zone.addEventListener("click", () => picker.click());
    picker.addEventListener("change", () => submit(picker.files[0]));
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("border-emerald-500"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("border-emerald-500"));
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("border-emerald-500");
      submit(e.dataTransfer.files[0]);
    });

    const cancel = h("button", "w-full rounded border border-neutral-800 py-2 text-xs text-neutral-300 hover:bg-neutral-900", "Cancel");
    cancel.addEventListener("click", onCancel);
    root.append(
      h("div", "text-xs text-neutral-400", message || "Upload the course syllabus PDF to extract its grading scheme."),
      name, zone, picker, cancel
    );
    return root;
  }

  function message(text) {
    return h("div", "p-6 text-center text-xs text-neutral-500", text);
  }

  return { h, home, courseDetail, dropzone, message };
})();
