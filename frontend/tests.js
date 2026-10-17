// Run from frontend/:  node tests.js
// Covers the pure logic (score parsing, URL classification, grade matching). DOM scraping needs a real Brightspace page.
const assert = require("node:assert/strict");
const content = require("./content.js");
const Grades = require("./js/grades.js");

// ---- parseScore ----
assert.deepEqual(content.parseScore("5.5 / 5.5"), { score: 5.5, max: 5.5 });
assert.deepEqual(content.parseScore("5.5/5.5"), { score: 5.5, max: 5.5 });
assert.deepEqual(content.parseScore("  85 / 100\n85 %"), { score: 85, max: 100 });
assert.deepEqual(content.parseScore("- / 10"), { score: null, max: 10 });
assert.deepEqual(content.parseScore("7,5 / 10"), { score: 7.5, max: 10 });
assert.equal(content.parseScore("85 %"), null);
assert.equal(content.parseScore("3 / 0"), null);
assert.equal(content.parseScore(""), null);

// ---- org id ----
assert.equal(content.getOrgId("https://brightspace.carleton.ca/d2l/lms/grades/my_grades/main.d2l?ou=123456"), "123456");
assert.equal(content.getOrgId("https://brightspace.carleton.ca/d2l/le/content/777/viewContent/9/View"), "777");
assert.equal(content.getOrgId("https://brightspace.carleton.ca/d2l/home"), null);

// ---- classifyUrls ----
const base = "https://brightspace.carleton.ca/d2l/le/content/777/viewContent/9/View";
const c = content.classifyUrls(
  [
    "/content/enforced/777-COMP1805/notes.pdf?ou=777",
    "/content/enforced/777-COMP1805/Course%20Outline.pdf",
    "/d2l/common/viewer.html?file=%2Fcontent%2Fenforced%2F777%2Fsyllabus.pdf",
    "https://docs.google.com/document/d/abc/edit",
    "mailto:a@b.ca",
    "/d2l/home/777",
  ],
  base,
);
assert.equal(c.pdfs.length, 3);
assert.match(c.pdfs[0], /Course%20Outline|syllabus/i); // preferred names sort first
assert.ok(c.pdfs.includes("https://brightspace.carleton.ca/content/enforced/777/syllabus.pdf")); // unwrapped viewer
assert.deepEqual(c.external, ["https://docs.google.com/document/d/abc/edit"]);
assert.equal(content.isPdf(new TextEncoder().encode("%PDF-1.7 ...")), true);
assert.equal(content.isPdf(new TextEncoder().encode("<html>")), false);
assert.equal(Buffer.from(content.bytesToBase64(new Uint8Array([1, 2, 3])), "base64").length, 3);

// ---- Grades.matchGrades ----
const cats = [
  { name: "Quizzes", weight: 50, item_weight: 5.5, items: [1, 2, 3].map((n) => ({ name: "Quiz " + n })) },
  { name: "Lecture Engagement", weight: 10, item_weight: 1, items: [1, 2].map((n) => ({ name: "Lecture Engagement " + n })) },
  { name: "Final Exam", weight: 20, items: [{ name: "Final Exam" }] },
];
const r = Grades.matchGrades(cats, [
  { name: "Quiz 1", score: 5.5, max: 5.5 },
  { name: "Quiz 2", score: 4, max: 5.5 },
  { name: "Quiz 3", score: null, max: 5.5 }, // ungraded -> ignored
  { name: "Lecture Engagement 2", score: 1, max: 1 },
  { name: "Final Exam (20%)", score: 90, max: 100 },
  { name: "Quizzes", score: 9.5, max: 11 }, // folder total: must not clobber a numbered quiz
  { name: "Bonus Drill", score: 1, max: 1 },
]);
assert.equal(r.matched, 4);
assert.deepEqual(r.categories[0].items[0], { name: "Quiz 1", score: 5.5, max_score: 5.5 });
assert.deepEqual(r.categories[0].items[1], { name: "Quiz 2", score: 4, max_score: 5.5 });
assert.equal(r.categories[0].items[2].score, undefined);
assert.equal(r.categories[1].items[0].score, undefined); // number mismatch never matches
assert.equal(r.categories[1].items[1].score, 1);
assert.deepEqual(r.categories[2].items[0], { name: "Final Exam", score: 90, max_score: 100 });
assert.deepEqual(r.unmatched.sort(), ["Bonus Drill", "Quizzes"]);
assert.equal(cats[0].items[0].score, undefined); // input untouched

// ---- Grades.carryScores ----
const carried = Grades.carryScores(r.categories, cats);
assert.equal(carried[0].items[1].score, 4);
assert.equal(carried[2].items[0].max_score, 100);

console.log("frontend tests passed");
