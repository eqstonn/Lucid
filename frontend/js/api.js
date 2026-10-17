/* Client for the local FastAPI backend. */
const Api = (() => {
  const BASE = "http://localhost:8000";

  async function request(path, init) {
    let res;
    try {
      res = await fetch(BASE + path, init);
    } catch (err) {
      throw new Error("Cannot reach the Lucid backend at " + BASE + ". Is uvicorn running?");
    }
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        if (typeof body.detail === "string") detail = body.detail;
        else if (body.detail) detail = JSON.stringify(body.detail);
      } catch (_) { /* non-JSON error body */ }
      throw new Error(detail || "Request failed (" + res.status + ")");
    }
    return res.json();
  }

  /** Upload a PDF (File/Blob) as multipart; resolves to the GradingCategory[] list. */
  async function parseSyllabus(file) {
    const form = new FormData();
    form.append("file", file, file.name || "syllabus.pdf");
    const data = await request("/api/parse-syllabus", { method: "POST", body: form });
    return data.categories;
  }

  /** Resolves to a CourseStanding for the given categories. */
  function calculateStanding(categories) {
    return request("/api/calculate-standing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ categories }),
    });
  }

  return { parseSyllabus, calculateStanding };
})();
