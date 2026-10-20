const $ = (id) => document.getElementById(id);
const send = (msg) => new Promise((resolve) => chrome.runtime.sendMessage(msg, resolve));
const LABELS = { idle:"Idle", running:"Running", needs_human:"NEEDS YOU", paused:"Paused", done:"Done", stopped:"Stopped" };

async function render() {
  const { state, bills, githubReadToken, githubWriteToken } = await chrome.storage.local.get(["state","bills","githubReadToken","githubWriteToken"]);
  const s = state || { status:"idle", next:1, log:[], paginate:false };
  const list = Object.values(bills || {});
  let text = LABELS[s.status] || s.status;
  if (s.status === "running" || s.status === "needs_human") text += ` — bill ${s.next}`;
  if (s.message) text += `\n${s.message}`;
  $("status").className = "status " + s.status;
  $("status").textContent = text;
  $("paginate").checked = !!s.paginate;
  $("readToken").value = githubReadToken || "";
  $("writeToken").value = githubWriteToken || "";
  const highest = list.reduce((m,b)=>Math.max(m,Number(b.resolution_id)||0),0);
  $("counts").textContent = `${list.length} bills stored (highest #${highest}), ${list.filter(b=>b.finalized).length} final`;
  $("log").textContent = (s.log || []).join("\n");
  $("log").scrollTop = $("log").scrollHeight;
}

$("start").onclick = () => send({ type: $("paginate").checked ? "startPagination" : "stopPagination" });
$("paginate").onchange = () => send({ type: $("paginate").checked ? "startPagination" : "stopPagination" });
$("pause").onclick = () => send({type:"pause"});
$("resume").onclick = () => send({type:"resume"});
$("stop").onclick = () => send({type:"stopPagination"});
$("saveTokens").onclick = async () => { await send({type:"saveTokens", readToken:$("readToken").value.trim(), writeToken:$("writeToken").value.trim()}); alert("Tokens saved to Chrome local extension storage."); };
$("sync").onclick = async () => { const r = await send({type:"sync"}); if (!r?.ok) alert(r?.error || "Sync failed"); };
$("export").onclick = async () => { const r = await send({type:"export"}); const list = r?.bills || []; if (!list.length) return alert("Nothing to export yet."); const blob = new Blob([JSON.stringify(list,null,2)+"\n"],{type:"application/json"}); const a=document.createElement("a"); a.href=URL.createObjectURL(blob); a.download="bills.json"; a.click(); URL.revokeObjectURL(a.href); };
$("import").onclick = () => $("file").click();
$("file").onchange = async (e) => { const f=e.target.files[0]; if(!f)return; try { const incoming=JSON.parse(await f.text()); const {bills}=await chrome.storage.local.get("bills"); const all=bills||{}; for(const b of incoming) all[b.resolution_id]=b; await chrome.storage.local.set({bills:all}); } catch(err){alert("Could not read file: "+err.message)} e.target.value=""; render(); };
$("clear").onclick = async () => { if(confirm("Delete all local bills and scraper state?")){ await chrome.storage.local.remove(["bills","state"]); render(); } };
chrome.storage.onChanged.addListener(render);
render();
