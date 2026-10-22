import { probe, extractBill, extractOffice, extractDiscovery } from "./inject.js";
import { buildBill } from "./parse.js";

const BASE = "https://powerplayusa.net";
const OWNER = "SK64HD";
const REPO = "ppusa-scorecard";
const BRANCH = "main";
const EXTENSION_PATH = "extension";
const LOCAL_VERSION = "3.2.0";
const DEFAULT_DELAY = 1200;
const UPDATE_CHECK_MS = 6 * 60 * 60 * 1000;
const DISCOVERY_KEY = "ppusaDiscovery";
const DISCOVERY_MAX = 50;

let looping = false;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function state() {
  const { scraperState } = await chrome.storage.local.get("scraperState");
  return scraperState || { status: "idle", next: 1, log: [], tabId: null };
}
async function setState(patch) {
  const current = await state();
  const next = { ...current, ...patch };
  await chrome.storage.local.set({ scraperState: next });
  return next;
}
async function log(line) {
  const current = await state();
  current.log = [...(current.log || []), `${new Date().toLocaleTimeString()}  ${line}`].slice(-150);
  await chrome.storage.local.set({ scraperState: current });
}
async function token() {
  const { apiToken } = await chrome.storage.local.get("apiToken");
  return String(apiToken || "").trim();
}
function githubHeaders(apiToken, json = false) {
  const headers = { Accept: "application/vnd.github+json" };
  if (apiToken) headers.Authorization = `Bearer ${apiToken}`;
  if (json) headers["Content-Type"] = "application/json";
  return headers;
}
function versionParts(version) {
  return String(version || "0").replace(/^v/i, "").split(".").map(x => Number.parseInt(x, 10) || 0).slice(0, 3);
}
function isNewerVersion(remote, local) {
  const a = versionParts(remote);
  const b = versionParts(local);
  for (let i = 0; i < 3; i++) {
    if (a[i] !== b[i]) return a[i] > b[i];
  }
  return false;
}
async function githubFile(path) {
  const apiToken = await token();
  if (!apiToken) throw new Error("Paste the API token in the extension first.");
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${path}?ref=${BRANCH}`;
  const response = await fetch(url, { headers: githubHeaders(apiToken) });
  if (!response.ok) throw new Error(`GitHub read ${path} failed (${response.status})`);
  const data = await response.json();
  const bytes = Uint8Array.from(atob(data.content.replace(/\n/g, "")), c => c.charCodeAt(0));
  return { sha: data.sha, text: new TextDecoder().decode(bytes) };
}
async function githubWriteText(path, text, message) {
  const apiToken = await token();
  if (!apiToken) throw new Error("Paste the API token in the extension first.");
  let sha = null;
  try { sha = (await githubFile(path)).sha; } catch (error) {
    if (!String(error.message).includes("(404)")) throw error;
  }
  const bytes = new TextEncoder().encode(String(text));
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  const content = btoa(binary);
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${path}`;
  const body = { message, content, branch: BRANCH };
  if (sha) body.sha = sha;
  const response = await fetch(url, { method: "PUT", headers: githubHeaders(apiToken, true), body: JSON.stringify(body) });
  if (!response.ok) throw new Error(`GitHub write ${path} failed (${response.status})`);
  return response.json();
}
async function githubWrite(path, value, message) {
  const text = JSON.stringify(value, null, 2) + "\n";
  return githubWriteText(path, text, message);
}
async function runUpdateAction(remoteVersion) {
  const action = {
    ranAt: new Date().toISOString(),
    localVersion: LOCAL_VERSION,
    remoteVersion,
    action: "update-available",
    instructions: "Download the matching GitHub release or replace/reload the unpacked extension files."
  };
  await chrome.storage.local.set({ extensionUpdateAction: action });
  await chrome.action.setBadgeText({ text: "NEW" }).catch(() => {});
  await chrome.action.setBadgeBackgroundColor({ color: "#b91c1c" }).catch(() => {});
  await log(`Update action ran for ${LOCAL_VERSION} → ${remoteVersion}. Badge set to NEW.`);
}
async function checkForUpdate({ notify = false } = {}) {
  const apiToken = await token();
  if (!apiToken) return { configured: false, update: false, local: LOCAL_VERSION };
  try {
    const remote = JSON.parse((await githubFile(`${EXTENSION_PATH}/manifest.json`)).text);
    const remoteVersion = String(remote.version || "0.0.0");
    const update = isNewerVersion(remoteVersion, LOCAL_VERSION);
    await chrome.storage.local.set({
      extensionUpdate: {
        localVersion: LOCAL_VERSION,
        remoteVersion,
        update,
        checkedAt: new Date().toISOString(),
        path: EXTENSION_PATH
      }
    });
    if (update) {
      const { extensionUpdateAction } = await chrome.storage.local.get("extensionUpdateAction");
      if (extensionUpdateAction?.remoteVersion !== remoteVersion) await runUpdateAction(remoteVersion);
    } else if (notify) {
      await log(`Extension is current at version ${LOCAL_VERSION}.`);
      await chrome.action.setBadgeText({ text: "" }).catch(() => {});
    }
    return { configured: true, update, local: LOCAL_VERSION, remote: remoteVersion };
  } catch (error) {
    await log(`Update check failed: ${error.message}`);
    return { configured: true, update: false, local: LOCAL_VERSION, error: error.message };
  }
}
async function syncBill(bill) {
  const remote = JSON.parse((await githubFile("bills.json")).text);
  const map = Object.fromEntries(remote.map(x => [String(x.resolution_id), x]));
  map[String(bill.resolution_id)] = bill;
  const merged = Object.values(map).sort((a, b) => Number(a.resolution_id) - Number(b.resolution_id));
  await githubWrite("bills.json", merged, `Update bill ${bill.resolution_id} from PPUSA extension`);
  await log(`saved bill ${bill.resolution_id} to bills.json`);
}
async function syncOffice(office) {
  const remote = JSON.parse((await githubFile("offices.json")).text || "{}");
  remote.profiles = remote.profiles || {};
  remote.profiles[String(office.profile_id)] = office.record;
  remote.generated_at = new Date().toISOString();
  await githubWrite("offices.json", remote, `Update office ${office.profile_id} from PPUSA extension`);
  await log(`saved office ${office.profile_id} to offices.json`);
}
async function tabAlive(tabId) {
  try { await chrome.tabs.get(tabId); return true; } catch { return false; }
}
async function inspect(tabId) {
  try {
    const [result] = await chrome.scripting.executeScript({ target: { tabId }, func: probe });
    return result?.result || null;
  } catch { return null; }
}
async function scrapeBillTab(tabId) {
  const p = await inspect(tabId);
  if (!p) return { kind: "unavailable" };
  if (p.challenge) return { kind: "challenge" };
  if (p.notFound) return { kind: "404" };
  if (!p.isBill) return { kind: "other" };
  const [result] = await chrome.scripting.executeScript({ target: { tabId }, func: extractBill });
  if (!result?.result?.found) return { kind: "other" };
  const match = p.path.match(/\/resolutions\/(\d+)/);
  const id = match ? Number(match[1]) : null;
  return id ? { kind: "bill", bill: buildBill(result.result, id) } : { kind: "other" };
}
async function scrapeOfficeTab(tabId) {
  const p = await inspect(tabId);
  if (!p || !p.isWiki) return { kind: "other" };
  if (p.challenge) return { kind: "challenge" };
  const [result] = await chrome.scripting.executeScript({ target: { tabId }, func: extractOffice });
  const match = p.path.match(/\/politician\/(\d+)/);
  if (!match || !result?.result) return { kind: "other" };
  return { kind: "office", office: { profile_id: match[1], record: result.result } };
}
async function discoverTab(tabId) {
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  if (!tab?.url || !tab.url.startsWith(`${BASE}/`)) return { found: false, reason: "outside-ppusa" };
  try {
    const [result] = await chrome.scripting.executeScript({ target: { tabId }, func: extractDiscovery });
    const hit = result?.result;
    if (!hit?.found) return { found: false };
    const captures = (await chrome.storage.local.get(DISCOVERY_KEY))[DISCOVERY_KEY] || [];
    const encoder = new TextEncoder();
    const digest = await crypto.subtle.digest("SHA-256", encoder.encode(hit.source));
    const hash = [...new Uint8Array(digest)].map(x => x.toString(16).padStart(2, "0")).join("").slice(0, 16);
    if (!captures.some(x => x.hash === hash)) {
      captures.push({
        hash,
        url: hit.url,
        path: hit.path,
        title: hit.title,
        pageType: hit.pageType,
        hits: hit.hits,
        keywordCount: hit.keywordCount,
        capturedAt: hit.capturedAt,
        source: hit.source,
        synced: false
      });
      while (captures.length > DISCOVERY_MAX) captures.shift();
      await chrome.storage.local.set({ [DISCOVERY_KEY]: captures });
      await log(`Discovery hit: ${hit.pageType} — ${hit.path} — ${Object.keys(hit.hits).join(", ")}.`);
    }
    return { found: true, hit };
  } catch (error) {
    await log(`Discovery error: ${error.message}`);
    return { found: false, error: error.message };
  }
}
async function syncDiscovery() {
  const captures = (await chrome.storage.local.get(DISCOVERY_KEY))[DISCOVERY_KEY] || [];
  let synced = 0;
  for (const capture of captures) {
    if (capture.synced) continue;
    const safePath = capture.path.replace(/^\//, "").replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 100) || "page";
    const filePath = `examples/extension-captures/${safePath}-${capture.hash}.txt`;
    const header = [
      "PPUSA extension discovery capture",
      `Captured: ${capture.capturedAt}`,
      `URL: ${capture.url}`,
      `Path: ${capture.path}`,
      `Title: ${capture.title}`,
      `Page type: ${capture.pageType}`,
      `Keyword hits: ${JSON.stringify(capture.hits)}`,
      "",
      "----- SOURCE -----",
      ""
    ].join("\n");
    await githubWriteText(filePath, header + capture.source + "\n", `Add PPUSA discovery capture ${capture.hash}`);
    capture.synced = true;
    synced += 1;
  }
  await chrome.storage.local.set({ [DISCOVERY_KEY]: captures });
  await log(`Synced ${synced} discovery capture(s) to examples/extension-captures/.`);
  return { synced, remaining: captures.filter(x => !x.synced).length };
}
async function visitBill(tabId, id) {
  await chrome.tabs.update(tabId, { url: `${BASE}/resolutions/${id}`, active: false });
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (!(await tabAlive(tabId))) return { kind: "closed" };
    const result = await scrapeBillTab(tabId);
    if (["bill", "404", "challenge"].includes(result.kind)) return result;
    await sleep(600);
  }
  return { kind: "timeout" };
}
async function paginateBills() {
  if (looping) return;
  const current = await state();
  if (!current.paginate) return;
  looping = true;
  try {
    let highest = Number(current.next || 0);
    if (!highest) {
      try {
        const remote = JSON.parse((await githubFile("bills.json")).text);
        highest = Math.max(0, ...remote.map(x => Number(x.resolution_id) || 0));
      } catch (_) { highest = 0; }
    }
    let id = highest + 1;
    let tabId = current.tabId;
    if (!tabId || !(await tabAlive(tabId))) {
      const tab = await chrome.tabs.create({ url: `${BASE}/resolutions/${id}`, active: false });
      tabId = tab.id;
      await setState({ tabId });
    }
    await setState({ status: "running", next: id });
    while (true) {
      const result = await visitBill(tabId, id);
      if (result.kind === "bill") {
        await syncBill(result.bill);
        id += 1;
        await setState({ next: id });
        await sleep(DEFAULT_DELAY);
        continue;
      }
      if (result.kind === "404") {
        await setState({ status: "done", next: id, message: `Pagination stopped at 404 after bill ${id - 1}.` });
        await log(`pagination reached 404 at ${id}; stopped`);
        break;
      }
      if (result.kind === "challenge") {
        await setState({ status: "needs_human", next: id, message: `Security check on bill ${id}. Solve it in the scraper tab.` });
        break;
      }
      await setState({ status: "paused", next: id, message: `Stopped on bill ${id}: ${result.kind}.` });
      break;
    }
  } catch (error) {
    await setState({ status: "error", message: error.message });
    await log(`ERROR: ${error.message}`);
  } finally {
    looping = false;
  }
}
async function scrapeCurrent(tabId) {
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  if (!tab?.url?.startsWith(`${BASE}/`)) return;
  const bill = await scrapeBillTab(tabId);
  if (bill.kind === "bill") {
    try { await syncBill(bill.bill); } catch (error) { await log(`Bill sync error: ${error.message}`); }
    return;
  }
  const office = await scrapeOfficeTab(tabId);
  if (office.kind === "office") {
    try { await syncOffice(office.office); } catch (error) { await log(`Office sync error: ${error.message}`); }
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    if (msg.type === "saveToken") {
      await chrome.storage.local.set({ apiToken: String(msg.token || "").trim() });
      await log("API token saved locally in Chrome extension storage.");
      await checkForUpdate({ notify: false });
    } else if (msg.type === "checkForUpdate") {
      const result = await checkForUpdate({ notify: true });
      sendResponse({ ok: !result.error, ...result });
      return;
    } else if (msg.type === "setBackgroundMode") {
      const enabled = Boolean(msg.enabled);
      await chrome.storage.local.set({ backgroundMode: enabled });
      await log(`Background discovery ${enabled ? "enabled" : "disabled"}.`);
      sendResponse({ ok: true, enabled });
      return;
    } else if (msg.type === "syncDiscovery") {
      const result = await syncDiscovery();
      sendResponse({ ok: true, ...result });
      return;
    } else if (msg.type === "clearDiscovery") {
      await chrome.storage.local.set({ [DISCOVERY_KEY]: [] });
      await log("Local discovery captures cleared.");
    } else if (msg.type === "startPagination") {
      await setState({ paginate: true, status: "running", message: "Paginating bills until the first 404." });
      paginateBills();
    } else if (msg.type === "stopPagination") {
      await setState({ paginate: false, status: "idle", message: "Pagination stopped." });
    } else if (msg.type === "scrapeCurrent") {
      if (!sender.tab?.id) throw new Error("Open a PPUSA bill or politician wiki page first.");
      await scrapeCurrent(sender.tab.id);
    } else if (msg.type === "syncAll") {
      await log("Manual sync uses the current remote JSONs and the active page.");
      if (sender.tab?.id) await scrapeCurrent(sender.tab.id);
    } else if (msg.type === "export") {
      const remoteBills = JSON.parse((await githubFile("bills.json")).text);
      const remoteOffices = JSON.parse((await githubFile("offices.json")).text);
      sendResponse({ ok: true, bills: remoteBills, offices: remoteOffices });
      return;
    }
    sendResponse({ ok: true });
  })().catch(async error => { await log(`ERROR: ${error.message}`); sendResponse({ ok: false, error: error.message }); });
  return true;
});

chrome.runtime.onStartup.addListener(() => { checkForUpdate({ notify: true }); });
chrome.runtime.onInstalled.addListener(() => { checkForUpdate({ notify: true }); });

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (changeInfo.status !== "complete") return;
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  if (!tab?.url?.startsWith(`${BASE}/`)) return;
  const s = await state();
  if (s.paginate && tabId === s.tabId) return;
  await scrapeCurrent(tabId);
  const { backgroundMode } = await chrome.storage.local.get("backgroundMode");
  if (backgroundMode) await discoverTab(tabId);
});

setInterval(() => { checkForUpdate({ notify: true }); }, UPDATE_CHECK_MS);
