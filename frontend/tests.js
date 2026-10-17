// Run from frontend/:  node tests.js
// Covers the pure logic (score parsing, URL classification, grade matching). DOM scraping needs a real Brightspace page.
const assert = require("node:assert/strict");
const content = require("./content.js");
const Grades = require("./js/grades.js");

// ---- parseScore ----
assert.deepEqual(content.parseScore("5.5 / 5.5"), { score: 5.5, max: 5.5 });
assert.deepEqual(content.parseScore("5.5/5.5"), { score: 5.5, max: 5.5 });
assert.deepEqual(content.parseScore("  12 /\n 12 "), { score: 12, max: 12 });
assert.deepEqual(content.parseScore("0 / 30\nDropped!"), { score: 0, max: 30 }); // trailing text ignored
assert.deepEqual(content.parseScore("\n\n   23 / 30  ⓘ "), { score: 23, max: 30 }); // whitespace/icons ignored
assert.deepEqual(content.parseScore("Points: 1.5 / 2 (75 %)"), { score: 1.5, max: 2 }); // not "5 / 2"
assert.deepEqual(content.parseScore("\n  -  \n / 10\nNot yet graded"), { score: null, max: 10 });
assert.equal(content.parseScore("0.5 %"), null);
assert.equal(content.parseScore("n/a"), null);
assert.deepEqual(content.parseScore("- / 10"), { score: null, max: 10 });
assert.deepEqual(content.parseScore("7,5 / 10"), { score: 7.5, max: 10 });
assert.equal(content.parseScore("85 %"), null);
assert.equal(content.parseScore("3 / 0"), null);
assert.equal(content.parseScore(""), null);

// ---- grades table: columns by header, nested rows, category rows skipped ----
assert.deepEqual(content.locateColumns(["Grade Item", "Points", "Weight Achieved", "Grade"]), { name: 0, points: 1 });
assert.deepEqual(content.locateColumns(["", "Grade Item  Sort", "Weight Achieved", "Points"]), { name: 1, points: 3 });
assert.equal(content.locateColumns(["Assignment 1", "12 / 12"]), null);
const table = [
  ["Grade Item", "Points", "Weight Achieved", "Grade"],
  ["Labs", "", "4 / 10", "40 %"], // category: Points empty, weight column must be ignored
  ["   Lab 1\n", "12 / 12", "2 / 5", "100 %"], // indented child
  ["  Lab 2", "- / 10", "- / 5", "-"], // ungraded
  ["Assignment 1", "0.5 / 0.5", "1 / 1", "100 %"], // flat
  ["Assignments", "20 / 40", "5 / 10", "50 %"].map((c, i) => (i === 1 ? "" : c)),
  ["Bonus", "n/a", "", ""],
  ["Short row"],
];
assert.deepEqual(content.gradesFromRows(table), [
  { name: "Lab 1", score: 12, max: 12 },
  { name: "Lab 2", score: null, max: 10 },
  { name: "Assignment 1", score: 0.5, max: 0.5 },
]);
// The MATH1005 grades page: innerText\ntextContent doubled cells, dropped item, category rows without points.
const math = [
  ["Grade Item", "Points", "Weight Achieved", "Grade", "Comments and Assessments"],
  ["Term\nTerm", "", "25.5 / 45\n25.5 / 45", "56.67 %", ""],
  ["Test 1\nTest 1", "23 / 30\n23 / 30", "11.5 / 15", "76.67 %", ""],
  ["Test 3", "0 / 30 ⓘ\nDropped!\n0 / 30 Dropped!", "0 / 0", "0 %", ""],
  ["Test 4", "0 / 30", "0 / 15", "0 %", ""],
  ["Exam", "", "0 / 55", "0 %", ""],
  ["Exam", "0 / 100", "0 / 55", "0 %", ""],
];
assert.deepEqual(content.gradesFromRows(math), [
  { name: "Test 1", score: 23, max: 30 },
  { name: "Test 3", score: null, max: 30 }, // dropped -> ungraded, not a zero
  { name: "Test 4", score: 0, max: 30 },
  { name: "Exam", score: 0, max: 100 },
]);
// Indented child rows carry a blank spacer cell first (6 cells vs the header's 5): columns shift right.
const spaced = [
  ["Grade Item", "Points", "Weight Achieved", "Grade", "Comments and Assessments"],
  ["Term", "", "25.5 / 45", "56.67 %", ""],
  ["", "Test 1", "23 / 30", "11.5 / 15", "76.67 %", ""],
  ["  ", "Test 2", "28 / 30", "14 / 15", "93.33 %", ""],
  ["", "Test 3", "0 / 30\nDropped!", "0 / 0", "0 %", ""],
  ["", "", "Sub item", "4 / 5", "1 / 1", "80 %", ""], // two spacers
  ["", "Test 4", "- / 30", "0 / 15", "0 %", ""],
  ["Exam", "", "0 / 55", "0 %", ""],
  ["", "Exam", "0 / 100", "0 / 55", "0 %", ""],
];
assert.deepEqual(content.gradesFromRows(spaced), [
  { name: "Test 1", score: 23, max: 30 },
  { name: "Test 2", score: 28, max: 30 },
  { name: "Test 3", score: null, max: 30 },
  { name: "Sub item", score: 4, max: 5 },
  { name: "Test 4", score: null, max: 30 },
  { name: "Exam", score: 0, max: 100 },
]);
// A header with its own leading blank column (e.g. a checkbox) must not cause a shift on data rows that share it.
assert.deepEqual(
  content.gradesFromRows([["", "Grade Item", "Points"], ["", "Quiz 1", "3 / 4"], ["", "", "Quiz 2", "1 / 4"]]),
  [{ name: "Quiz 1", score: 3, max: 4 }, { name: "Quiz 2", score: 1, max: 4 }],
);
// No header row: standard order (name, points) is assumed.
assert.deepEqual(content.gradesFromRows([["Quiz 1", "5.5 / 5.5", "x"]]), [{ name: "Quiz 1", score: 5.5, max: 5.5 }]);
// Reordered columns are followed, and the Weight Achieved column is never used as points.
assert.deepEqual(
  content.gradesFromRows([["Weight Achieved", "Grade Item", "Points"], ["1 / 1", "Quiz 1", "- / 10"]]),
  [{ name: "Quiz 1", score: null, max: 10 }],
);

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
