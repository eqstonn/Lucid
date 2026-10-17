/* chrome.storage.local cache.
 * Shape: { courses: { [id]: Course } }
 * Course: { id, name, brightspaceId?: string (org-unit id), categories: GradingCategory[],
 *           standing: CourseStanding|null, updatedAt: number }
 */
const Store = (() => {
  const KEY = "lucid.courses";

  async function all() {
    const res = await chrome.storage.local.get(KEY);
    return res[KEY] || {};
  }

  async function list() {
    return Object.values(await all()).sort((a, b) => a.name.localeCompare(b.name));
  }

  async function get(id) {
    return (await all())[id] || null;
  }

  async function put(course) {
    const courses = await all();
    courses[course.id] = { ...course, updatedAt: Date.now() };
    await chrome.storage.local.set({ [KEY]: courses });
    return courses[course.id];
  }

  async function remove(id) {
    const courses = await all();
    delete courses[id];
    await chrome.storage.local.set({ [KEY]: courses });
  }

  function newId() {
    return crypto.randomUUID();
  }

  return { list, get, put, remove, newId };
})();
