(()=>{
'use strict';
const CFG='data/scorecard_sets_config.json',SETS='data/scorecard_sets.json',TARGET='data/conservative_scorecard.json';
let config=null,selected=null;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const originalFetch=window.fetch.bind(window);
async function getConfig(){if(!config)config=await originalFetch(CFG).then(r=>r.json());return config}
async function getSelected(){const c=await getConfig();const u=new URL(location.href);const q=u.searchParams.get('scorecard');selected=(c.sets||[]).some(s=>s.id===q)?q:(localStorage.getItem('ppusa-scorecard-set')&&c.sets.some(s=>s.id===localStorage.getItem('ppusa-scorecard-set'))?localStorage.getItem('ppusa-scorecard-set'):c.default_set||c.sets[0]?.id);return c.sets.find(s=>s.id===selected)||c.sets[0]}
window.fetch=async function(input,init){const url=typeof input==='string'?input:input?.url||'';if(url.includes(TARGET)){const set=await getSelected();const all=await originalFetch(SETS,init).then(r=>r.json());const chosen=all.sets?.find(x=>x.id===set.id);if(chosen)return new Response(JSON.stringify(chosen),{status:200,headers:{'Content-Type':'application/json'}})}return originalFetch(input,init)};
function installPicker(set){const old=document.getElementById('ppusa-set-picker');if(old)old.remove();const box=document.createElement('div');box.id='ppusa-set-picker';box.innerHTML=`<label>PPUSA-SCORECARD</label><select>${(config.sets||[]).map(s=>`<option value="${esc(s.id)}" ${s.id===set.id?'selected':''}>${esc(s.name)}</option>`).join('')}</select>`;Object.assign(box.style,{position:'absolute',right:'12px',top:'12px',left:'auto',zIndex:9999,background:'rgba(255,255,255,.96)',border:'1px solid #bbb',borderRadius:'8px',padding:'6px 8px',boxShadow:'0 2px 8px rgba(0,0,0,.12)',font:'12px system-ui'});box.querySelector('label').style.display='block';box.querySelector('select').style.maxWidth='220px';box.querySelector('select').onchange=e=>{localStorage.setItem('ppusa-scorecard-set',e.target.value);const u=new URL(location.href);u.searchParams.set('scorecard',e.target.value);location.href=u.toString()};document.body.appendChild(box)}
(async()=>{try{const set=await getSelected();installPicker(set);window.__PPUSA_SCORECARD_SET__=set}catch(e){console.warn('scorecard selector unavailable',e)}})();
})();
