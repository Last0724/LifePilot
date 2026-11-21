const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { test } = require("node:test");
const { createContext, runInContext } = require("node:vm");
const G = require("../ui/experience/guru.js");
const M = require("../ui/experience/model.js");

const EXAM = "exam-preparation-system";
const DEEP_WORK = "deep-work-master-plan";
const ULTIMATE = "ultimate-productivity-routine";
const DAY = "2026-11-16";
const NOW = new Date("2026-11-16T08:30:00");

function renderGuruGallery(state) {
  const window = { LifePilotGuru: G, LifePilotModel: M, LifePilotGuruMedia: { portrait: "" } };
  const context = createContext({ window });
  for (const path of ["../ui/experience/guru_view.js", "../ui/experience/view.js"]) {
    runInContext(readFileSync(require.resolve(path), "utf8"), context);
  }
  return window.LifePilotViews({
    state: () => state, t: (en) => en, view: () => "guru", selection: () => null,
  }).dashboard("all");
}

test("Free members see all four marketplace cards alongside the three existing routines", () => {
  const html = renderGuruGallery(M.newState());
  assert.match(html, /Marketplace Free/);
  assert.equal([...html.matchAll(/class="lp-card lp-marketplace-card"/g)].length, 4);
  for (const title of ["Deep Work Master Plan", "Exam Preparation System", "Ultimate Productivity Routine", "Elite Weekly Planner"]) {
    assert.ok(html.includes(title), title);
  }
  assert.equal([...html.matchAll(/Premium · Locked/g)].length, 2);
  assert.equal([...html.matchAll(/data-action="guru-open"/g)].length, 3);
});

test("locked plans reveal only two blocks and cannot be selected on Free", () => {
  const state = M.newState();
  const catalog = G.marketplaceCatalog(state);
  assert.deepEqual(catalog.map(({ id, locked, preview }) => [id, locked, preview.length]), [
    [DEEP_WORK, false, 4], [EXAM, true, 2], [ULTIMATE, true, 2], ["elite-weekly-planner", false, 4],
  ]);
  const exam = catalog.find((item) => item.id === EXAM);
  assert.match(exam.preview[0][0], /Calculus practice set/);
  assert.deepEqual(G.selectMarketplaceTemplate(state, EXAM), { locked: true });
  assert.equal(Object.hasOwn(state, "guruMarketplace"), false);
  assert.deepEqual(G.selectMarketplaceTemplate(state, DEEP_WORK), { updated: true });
  assert.equal(G.marketplaceState(state).selectedTemplateId, DEEP_WORK);
});

test("simulated marketplace upgrade unlocks all four blocks and permits selection", () => {
  const state = M.newState();
  assert.deepEqual(G.setMarketplaceTier(state, "premium"), { updated: true });
  assert.ok(G.marketplaceCatalog(state).every((item) => !item.locked && item.preview.length === 4));
  assert.deepEqual(G.selectMarketplaceTemplate(state, EXAM), { updated: true });
  assert.deepEqual(G.selectMarketplaceTemplate(state, EXAM), {});
  assert.equal(G.marketplaceCatalog(state).find((item) => item.id === EXAM).selected, true);
});

test("downgrade relocks Premium plans and retains the last selection without granting access", () => {
  const state = M.newState();
  G.setMarketplaceTier(state, "premium");
  G.selectMarketplaceTemplate(state, EXAM);
  assert.deepEqual(G.setMarketplaceTier(state, "free"), { updated: true });
  const exam = G.marketplaceCatalog(state).find((item) => item.id === EXAM);
  assert.deepEqual(G.marketplaceState(state), { tier: "free", selectedTemplateId: EXAM });
  assert.equal(exam.locked, true);
  assert.equal(exam.selected, false);
  assert.equal(exam.preview.length, 2);
  assert.deepEqual(G.selectMarketplaceTemplate(state, EXAM), { locked: true });
});

test("version 1 browser saves default to Free and round-trip marketplace updates", () => {
  const legacy = M.newState();
  legacy.user.name = "Returning user";
  legacy.user.onboardingCompleted = true;
  G.update(legacy, "hyper", "unlock");
  G.update(legacy, "hyper", "start");
  let state = JSON.parse(JSON.stringify(legacy));
  assert.deepEqual(G.marketplaceState(state), { tier: "free", selectedTemplateId: null });
  assert.deepEqual(state, legacy);
  G.setMarketplaceTier(state, "premium");
  G.selectMarketplaceTemplate(state, ULTIMATE);
  state = JSON.parse(JSON.stringify(state));
  assert.deepEqual(G.marketplaceState(state), { tier: "premium", selectedTemplateId: ULTIMATE });
  const { guruMarketplace, ...restoredLegacy } = state;
  assert.deepEqual(restoredLegacy, legacy);
});

test("marketplace membership and HYPER access are independent", () => {
  const state = M.newState();
  assert.ok(G.update(state, "hyper", "unlock").updated);
  assert.ok(G.marketplaceCatalog(state).find((item) => item.id === EXAM).locked);
  const newMember = M.newState();
  G.setMarketplaceTier(newMember, "premium");
  assert.deepEqual(G.update(newMember, "hyper", "start"), {});
  G.setMarketplaceTier(state, "premium");
  G.setMarketplaceTier(state, "free");
  assert.ok(G.update(state, "hyper", "start").updated);
});

test("marketplace actions preserve calendar data, XP, rankings and course promotion state", () => {
  const state = M.newState();
  state.user.onboardingCompleted = true;
  for (const [id, startTime, endTime] of [["focus", "09:00", "10:00"], ["review", "10:00", "11:00"]]) {
    assert.ok(M.saveTask(state, {
      id, title: id, date: DAY, startTime, endTime, category: "Study", priority: "Medium", repeatWeekly: false,
    }, NOW).updated);
  }
  M.openDashboard(state, NOW);
  M.startDemo(state, NOW);
  M.setCompletion(state, "focus", DAY, true, NOW);
  G.takeCoursePromotion(state, DAY);
  const snapshot = structuredClone(state);
  const ranking = M.ranking(state);
  const xp = M.totalXP(state);

  G.selectMarketplaceTemplate(state, EXAM);
  G.selectMarketplaceTemplate(state, DEEP_WORK);
  G.setMarketplaceTier(state, "premium");
  G.selectMarketplaceTemplate(state, ULTIMATE);
  G.setMarketplaceTier(state, "free");

  const { guruMarketplace, ...existingData } = state;
  assert.deepEqual(existingData, snapshot);
  assert.deepEqual(M.ranking(state), ranking);
  assert.equal(M.totalXP(state), xp);
});
