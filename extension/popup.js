const $ = id => document.getElementById(id);
const send = msg => new Promise(resolve => chrome.runtime.sendMessage(msg, resolve));

async function render() {
  const { scraperState, apiToken, extensionUpdate, extensionUpdateAction, backgroundMode, ppusaDiscovery } = await chrome.storage.local.get(["scraperState", "apiToken", "extensionUpdate", "extensionUpdateAction", "backgroundMode", "ppusaDiscovery"]);
  const s = scraperState || { status: "idle", next: 1, log: [] };
  const captures = ppusaDiscovery || [];
  $("status").className = "status " + s.status;
  $("status").textContent = `${s.status}${s.next ? ` — bill ${s.next}` : ""}${s.message ? `\n${s.message}` : ""}`;
  $("token").value = apiToken || "";
  $("background").checked = Boolean(backgroundMode);
  $("counts").textContent = "Token: " + (apiToken ? "configured" : "not configured");
  $("log").textContent = (s.log || []).join("\n");
  $("log").scrollTop = $("log").scrollHeight;
  const unsynced = captures.filter(x => !x.synced).length;
  $("captureStatus").textContent = `Discovery captures: ${captures.length} local, ${unsynced} waiting to sync.`;
  if (!extensionUpdate) {
    $("updateStatus").textContent = apiToken ? "Update status: not checked yet." : "Update status: enter the token first.";
  } else if (extensionUpdate.update) {
    const action = extensionUpdateAction?.ranAt ? ` Update action ran ${new Date(extensionUpdateAction.ranAt).toLocaleString()}.` : "";
    $("updateStatus").textContent = `Update available: ${extensionUpdate.localVersion} → ${extensionUpdate.remoteVersion}. Replace/reload the extension files from the repository.${action}`;
  } else {
    $("updateStatus").textContent = `Extension current: ${extensionUpdate.localVersion} (repository ${extensionUpdate.remoteVersion}).`;
  }
}

$("save").onclick = async () => {
  const value = $("token").value.trim();
  if (!value) return alert("Paste the API token first.");
  const result = await send({ type: "saveToken", token: value });
  if (!result?.ok) return alert(result?.error || "Could not save token.");
  render();
};
$("update").onclick = async () => {
  const result = await send({ type: "checkForUpdate" });
  if (!result?.ok) return alert(result?.error || "Update check failed.");
  render();
};
$("background").onchange = async event => {
  const result = await send({ type: "setBackgroundMode", enabled: event.target.checked });
  if (!result?.ok) alert(result?.error || "Could not change background mode.");
  render();
};
$("syncCaptures").onclick = async () => {
  const result = await send({ type: "syncDiscovery" });
  if (!result?.ok) return alert(result?.error || "Capture sync failed.");
  render();
};
$("clearCaptures").onclick = async () => {
  const result = await send({ type: "clearDiscovery" });
  if (!result?.ok) alert(result?.error || "Could not clear captures.");
  render();
};
$("scrape").onclick = async () => {
  const result = await send({ type: "scrapeCurrent" });
  if (!result?.ok) alert(result?.error || "Scrape failed.");
  render();
};
$("paginate").onclick = async () => {
  const result = await send({ type: "startPagination" });
  if (!result?.ok) alert(result?.error || "Pagination failed to start.");
  render();
};
$("stop").onclick = async () => { await send({ type: "stopPagination" }); render(); };
$("export").onclick = async () => {
  const result = await send({ type: "export" });
  if (!result?.ok) return alert(result?.error || "Export failed.");
  const blob = new Blob([JSON.stringify({ bills: result.bills, offices: result.offices }, null, 2) + "\n"], { type: "application/json" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "ppusa-scraper-export.json"; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};
chrome.storage.onChanged.addListener(render);
render();
