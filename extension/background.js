import { probe, extractBill, extractPlayerBillLinks } from "./inject.js";
import { buildBill } from "./parse.js";

const BASE = "https://powerplayusa.net";
const OWNER = "SK64HD";
const REPO = "ppusa_conservative_scorecard";
const BRANCH = "main";
const MAX_MISSES = 5;
const DEFAULT_DELAY = 1500;
const POLL_MINUTES = 5;

let looping = false;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getState() {
  const { state } = await chrome.storage.local.get("state");
  return state || {
    status: "idle", next: 1, misses: 0, tabId: null, delay: DEFAULT_DELAY,
    log: [], message: "", paginate: false, queue: [], playerTabs: []
  };
}
async function setState(patch) {
  const s = { ...(await getState()), ...patch };
  await chrome.storage.local.set({ state: s });
  return s;
}
async function log(line) {
  const s = await getState();
  const lines = [...(s.log || []), `${new Date().toLocaleTimeString()}  ${line}`].slice(-120);
  await chrome.storage.local.set({ state: { ...s, log: lines } });
}
async function getBills() {
  const { bills } = await chrome.storage.local.get("bills");
  return bills || {};
}
function badge(text, color) {
  chrome.action.setBadgeText({ text });
  if (color) chrome.action.setBadgeBackgroundColor({ color });
}
async function notify(title, message) {
  try {
    await chrome.notifications.create({ type: "basic", iconUrl: "icon128.png", title, message, priority: 2, requireInteraction: true });
  } catch (_) {}
}
async function tabAlive(tabId) {
  try { await chrome.tabs.get(tabId); return true; } catch (_) { return false; }
}
async function safeProbe(tabId) {
  try {
    const [r] = await chrome.scripting.executeScript({ target: { tabId }, func: probe });
    return r?.result || null;
  } catch (_) { return null; }
}

function ghHeaders(token, json = false) {
  const h = { Accept: "application/vnd.github+json" };
  if (token) h.Authorization = `Bearer ${token}`;
  if (json) h["Content-Type"] = "application/json";
  return h;
}
async function getGithubTokens() {
  return await chrome.storage.local.get(["githubReadToken", "githubWriteToken"]);
}
async function githubGetBills() {
  const { githubReadToken, githubWriteToken } = await getGithubTokens();
  const token = githubReadToken || githubWriteToken;
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/bills.json?ref=${BRANCH}`;
  const r = await fetch(url, { headers: ghHeaders(token) });
  if (!r.ok) throw new Error(`GitHub read failed (${r.status})`);
  const j = await r.json();
  const bytes = Uint8Array.from(atob(j.content.replace(/\n/g, "")), c => c.charCodeAt(0));
  const text = new TextDecoder().decode(bytes);
  return { sha: j.sha, bills: JSON.parse(text) };
}
async function githubWriteBills(bills, message = "Update bills.json from PPUSA browser scraper") {
  const { githubWriteToken } = await getGithubTokens();
  if (!githubWriteToken) throw new Error("No GitHub write token configured.");
  const current = await githubGetBills();
  const text = JSON.stringify(bills, null, 2) + "\n";
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  const content = btoa(binary);
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/bills.json`;
  const r = await fetch(url, {
    method: "PUT",
    headers: ghHeaders(githubWriteToken, true),
    body: JSON.stringify({ message, content, sha: current.sha, branch: BRANCH })
  });
  if (!r.ok) throw new Error(`GitHub write failed (${r.status})`);
  return await r.json();
}

async function saveBill(bill) {
  const all = await getBills();
  const previous = all[bill.resolution_id];
  const oldFinal = previous?.finalized === true;
  const oldStatus = String(previous?.status || "").toLowerCase();
  const newFinal = bill.finalized === true;
  const newStatus = String(bill.status || "").toLowerCase();
  all[bill.resolution_id] = bill;
  await chrome.storage.local.set({ bills: all });

  if (newFinal && !oldFinal) {
    const outcome = newStatus.includes("fail") || newStatus.includes("failed") ? "failed" :
      (newStatus.includes("pass") || newStatus.includes("passed") || bill.passed ? "passed" : "finalized");
    await notify(`PPUSA bill ${outcome}`, `${bill.number || `Bill ${bill.resolution_id}`}: ${bill.title || "Bill finalized"}`);
  }

  try {
    await githubWriteBills(Object.values(all).sort((a, b) => Number(a.resolution_id) - Number(b.resolution_id)),
      `Update bill ${bill.resolution_id}`);
    await log(`saved bill ${bill.resolution_id} to GitHub`);
  } catch (e) {
    await log(`GitHub update pending: ${e.message}`);
  }
}

async function visit(tabId, id) {
  const targetPath = `/resolutions/${id}`;
  await chrome.tabs.update(tabId, { url: `${BASE}${targetPath}`, active: false });
  await sleep(900);
  let deadline = Date.now() + 15000;
  let announced = false;
  while (true) {
    const st = await getState();
    if (["paused", "idle", "stopped"].includes(st.status)) return { kind: "stopped" };
    if (!(await tabAlive(tabId))) return { kind: "closed" };
    const p = await safeProbe(tabId);
    if (p?.path.startsWith("/login")) return { kind: "login" };
    if (p?.path === targetPath) {
      if (p.challenge) {
        if (!announced) {
          announced = true;
          await setState({ status: "needs_human", message: `Bot check on bill ${id}. Solve it in the scraper tab.` });
          badge("!", "#c62828");
          await notify("PPUSA scraper needs you", `Solve the check on bill ${id}.`);
        }
        deadline = Date.now() + 15000;
      } else if (p.isBill) {
        if (announced) {
          announced = false;
          await setState({ status: "running", message: "" });
          badge("", null);
        }
        const [r] = await chrome.scripting.executeScript({ target: { tabId }, func: extractBill });
        if (r?.result?.found) return { kind: "bill", raw: r.result };
      }
    }
    if (Date.now() > deadline) return { kind: "other" };
    await sleep(announced ? 2000 : 700);
  }
}

async function scrapeCurrentTab(tabId) {
  const p = await safeProbe(tabId);
  if (!p || p.challenge) return;
  if (p.path.match(/^\/resolutions\/\d+\/?$/) && p.isBill) {
    const id = Number(p.path.match(/\d+/)[0]);
    const [r] = await chrome.scripting.executeScript({ target: { tabId }, func: extractBill });
    if (r?.result?.found) await saveBill(buildBill(r.result, id));
    return;
  }
  if (p.isPlayer) {
    const [r] = await chrome.scripting.executeScript({ target: { tabId }, func: extractPlayerBillLinks });
    const ids = [...new Set((r?.result || []).filter(Number.isInteger))];
    const bills = await getBills();
    const unresolved = ids.filter(id => !bills[id]?.finalized);
    if (unresolved.length) {
      const st = await getState();
      await setState({ queue: [...new Set([...(st.queue || []), ...unresolved])] });
      await log(`found ${unresolved.length} unresolved bill links on player page`);
      if (st.paginate) startLoop();
    }
  }
}

async function startLoop() {
  const st0 = await getState();
  if (!st0.paginate || looping) return;
  looping = true;
  try {
    while (true) {
      let st = await getState();
      if (st.status !== "running" || !st.paginate) break;
      const bills = await getBills();
      let queue = [...new Set(st.queue || [])].filter(id => !bills[id]?.finalized);
      if (!queue.length) {
        const highest = Math.max(0, ...Object.keys(bills).map(Number));
        const candidate = Math.max(1, highest + 1);
        queue = [candidate];
      }
      const id = queue.shift();
      await setState({ queue, next: id, misses: st.misses || 0 });
      let tabId = st.tabId;
      if (!tabId || !(await tabAlive(tabId))) {
        const tab = await chrome.tabs.create({ url: `${BASE}/resolutions/${id}`, active: false });
        tabId = tab.id;
        await setState({ tabId });
      }
      const res = await visit(tabId, id);
      st = await getState();
      if (st.status !== "running") break;
      if (res.kind === "closed") {
        await setState({ status: "paused", tabId: null, message: "Scraper tab closed." });
        break;
      }
      if (res.kind === "bill") {
        await saveBill(buildBill(res.raw, id));
        await setState({ misses: 0 });
      } else {
        const misses = (st.misses || 0) + 1;
        if (misses >= MAX_MISSES && !(st.queue || []).length) {
          await setState({ status: "paused", misses, message: "Pagination reached the end of available bills." });
          await notify("PPUSA pagination paused", "No more bill pages were found. Current bills remain saved.");
          break;
        }
        await setState({ misses });
      }
      await sleep((st.delay || DEFAULT_DELAY) + Math.random() * (st.delay || DEFAULT_DELAY) * 0.5);
    }
  } finally {
    looping = false;
    const s = await getState();
    if (s.status !== "needs_human") badge("", null);
  }
}

function startPagination() {
  setState({ status: "running", paginate: true, message: "Background pagination enabled." });
  badge("…", "#1565c0");
  startLoop();
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    if (msg.type === "startPagination") startPagination();
    else if (msg.type === "stopPagination") await setState({ status: "idle", paginate: false, message: "Pagination disabled." });
    else if (msg.type === "pause") await setState({ status: "paused", message: "Paused." });
    else if (msg.type === "resume") { await setState({ status: "running" }); startLoop(); }
    else if (msg.type === "saveTokens") {
      await chrome.storage.local.set({ githubReadToken: msg.readToken || "", githubWriteToken: msg.writeToken || "" });
      await log("GitHub token settings saved locally.");
    } else if (msg.type === "sync") {
      const remote = await githubGetBills();
      const local = await getBills();
      const merged = { ...remote.bills, ...local };
      await chrome.storage.local.set({ bills: merged });
      await githubWriteBills(Object.values(merged).sort((a,b) => Number(a.resolution_id)-Number(b.resolution_id)), "Sync bills.json from browser scraper");
      await log(`synced ${Object.keys(merged).length} bills with GitHub`);
    } else if (msg.type === "export") {
      const bills = await getBills();
      sendResponse({ ok: true, bills: Object.values(bills).sort((a,b) => Number(a.resolution_id)-Number(b.resolution_id)) });
      return;
    }
    sendResponse({ ok: true });
  })().catch(async e => { await log(`ERROR: ${e.message}`); sendResponse({ ok: false, error: e.message }); });
  return true;
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (changeInfo.status === "complete") await scrapeCurrentTab(tabId);
});
chrome.tabs.onActivated.addListener(async ({ tabId }) => { await scrapeCurrentTab(tabId); });
chrome.alarms.create("billPoll", { periodInMinutes: POLL_MINUTES });
chrome.alarms.onAlarm.addListener(async ({ name }) => {
  if (name !== "billPoll") return;
  const tabs = await chrome.tabs.query({ url: "https://powerplayusa.net/*" });
  for (const tab of tabs) if (tab.id) await scrapeCurrentTab(tab.id);
  const st = await getState();
  if (st.paginate && st.status !== "needs_human") startLoop();
});
chrome.runtime.onStartup.addListener(async () => {
  const st = await getState();
  if (st.paginate) { await setState({ status: "running" }); startLoop(); }
});
