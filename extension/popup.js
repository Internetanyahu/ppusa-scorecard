const $ = id => document.getElementById(id);
const send = msg => new Promise(resolve => chrome.runtime.sendMessage(msg, resolve));

async function render() {
  const { scraperState, apiToken, extensionUpdate } = await chrome.storage.local.get(["scraperState", "apiToken", "extensionUpdate"]);
  const s = scraperState || { status: "idle", next: 1, log: [] };
  $("status").className = "status " + s.status;
  $("status").textContent = `${s.status}${s.next ? ` — bill ${s.next}` : ""}${s.message ? `\n${s.message}` : ""}`;
  $("token").value = apiToken || "";
  $("counts").textContent = "Token: " + (apiToken ? "configured" : "not configured");
  $("log").textContent = (s.log || []).join("\n");
  $("log").scrollTop = $("log").scrollHeight;
  if (!extensionUpdate) {
    $("updateStatus").textContent = apiToken ? "Update status: not checked yet." : "Update status: enter the token first.";
  } else if (extensionUpdate.update) {
    $("updateStatus").textContent = `Update available: ${extensionUpdate.localVersion} → ${extensionUpdate.remoteVersion}. Replace/reload the extension files from the repository.`;
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
