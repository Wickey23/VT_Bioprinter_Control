const $=id=>document.getElementById(id);
const state={token:sessionStorage.getItem("vt_token")||"",ssid:""};
async function api(path,opts={}){
  const headers={...(opts.headers||{}),"X-Bioprinter-Token":state.token};
  if(opts.body) headers["Content-Type"]="application/json";
  const r=await fetch(path,{...opts,headers});
  const d=await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(d.detail||("HTTP "+r.status));
  return d;
}
function pill(el,ok,text){el.textContent=text;el.className="pill "+(ok?"ok":"bad")}
function esc(s){return String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function uptime(s){if(s==null)return "—";const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);return [d?d+"d":"",h?h+"h":"",m+"m"].filter(Boolean).join(" ")}
async function status(){
  const s=await api("/api/status");
  $("sidebarDot").classList.add("online");$("sidebarStatus").textContent="Controller online";
  $("piState").textContent="ONLINE";$("piHost").textContent=s.hostname;
  $("printerState").textContent=s.printer.connected?"CONNECTED":"NOT CONNECTED";
  $("printerDevice").textContent=s.printer.device||"Awaiting lab connection";
  $("wifiState").textContent=s.network.ssid||"NOT CONNECTED";$("wifiIp").textContent=s.network.ip_address||"No IPv4";
  $("cpuTemp").textContent=s.cpu_temp_c==null?"—":s.cpu_temp_c+" °C";
  $("diskUsed").textContent=s.disk.used_gb+" / "+s.disk.total_gb+" GB";$("diskFree").textContent=s.disk.free_gb+" GB";
  $("diskBar").style.width=Math.min(100,s.disk.used_gb/s.disk.total_gb*100)+"%";
  $("heroStatus").textContent=s.printer.connected?"Printer link detected":"Host ready — printer not connected";
  $("heroSub").textContent=s.printer.connected?"Creality serial interface detected. Motion remains locked.":"Raspberry Pi services are online and waiting for the printer controller.";
  pill($("heroPill"),true,s.printer.connected?"PRINTER FOUND":"HOST READY");
  $("currentSsid").textContent=s.network.ssid||"Not connected";$("currentIp").textContent=s.network.ip_address||"—";
  $("currentSignal").textContent=s.network.signal==null?"—":s.network.signal+"%";$("currentSecurity").textContent=s.network.security||"—";
  pill($("wifiBadge"),s.network.connected,s.network.connected?"CONNECTED":"OFFLINE");
  $("systemDetails").innerHTML=[["Hostname",s.hostname],["Uptime",uptime(s.uptime_seconds)],["CPU temperature",s.cpu_temp_c+" °C"],["Storage free",s.disk.free_gb+" GB"],["IP address",s.network.ip_address||"—"]].map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");
}
async function printer(){
  const p=await api("/api/printer/status");pill($("printerConnectionBadge"),p.connected,p.connected?"CONNECTED":"NOT CONNECTED");
  const rows=p.selected?[["Device",p.selected.device],["Description",p.selected.description],["USB ID",(p.selected.vid||"—")+":"+(p.selected.pid||"—")]]:[["Device","—"],["Status","Waiting for Creality/CH340 USB connection"]];
  rows.push(["Motion","Locked until commissioning"]);
  $("printerDetails").innerHTML=rows.map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");
}
async function scan(){
  $("wifiList").innerHTML='<p class="muted">Scanning…</p>';
  const d=await api("/api/network/scan");
  $("wifiList").innerHTML=d.networks.map(n=>'<div class="wifi-item"><div class="wifi-meta"><strong>'+esc(n.ssid)+(n.in_use?" ✓":"")+'</strong><small>'+esc(n.security)+" · Signal "+n.signal+'%</small></div><button class="secondary join" data-s="'+esc(n.ssid)+'">Connect</button></div>').join("")||'<p class="muted">No networks found.</p>';
  document.querySelectorAll(".join").forEach(b=>b.onclick=()=>{state.ssid=b.dataset.s;$("dialogSsid").textContent=state.ssid;$("wifiPassword").value="";$("wifiDialogMessage").textContent="";$("wifiDialog").showModal()});
}
async function saved(){
  const d=await api("/api/network/saved");
  $("savedNetworks").innerHTML=d.connections.map(n=>'<div class="saved-item"><span>'+esc(n)+'</span><button data-n="'+esc(n)+'">Forget</button></div>').join("")||'<p class="muted">No saved Wi-Fi profiles.</p>';
  $("savedNetworks").querySelectorAll("button").forEach(b=>b.onclick=async()=>{if(confirm("Forget "+b.dataset.n+"?")){await api("/api/network/forget",{method:"POST",body:JSON.stringify({connection:b.dataset.n})});saved()}});
}
document.querySelectorAll(".nav-btn").forEach(b=>b.onclick=()=>{document.querySelectorAll(".nav-btn,.page").forEach(x=>x.classList.remove("active"));b.classList.add("active");$("page-"+b.dataset.page).classList.add("active");$("pageTitle").textContent=b.dataset.page[0].toUpperCase()+b.dataset.page.slice(1);if(b.dataset.page==="network")saved();if(b.dataset.page==="printer")printer()});
document.querySelectorAll(".safe-command").forEach(b=>b.onclick=async()=>{try{const d=await api("/api/printer/command",{method:"POST",body:JSON.stringify({command:b.dataset.command})});$("terminal").textContent=">>> "+d.command+"\n"+d.response.join("\n")}catch(e){$("terminal").textContent="ERROR: "+e.message}});
$("scanWifi").onclick=()=>scan().catch(e=>$("wifiList").textContent=e.message);
$("refreshPrinter").onclick=()=>printer();
$("refreshAll").onclick=()=>{status();printer()};
$("cancelWifi").onclick=()=>$("wifiDialog").close();
$("wifiForm").onsubmit=async e=>{e.preventDefault();$("wifiDialogMessage").textContent="Changing network… this page may disconnect.";try{await api("/api/network/connect",{method:"POST",body:JSON.stringify({ssid:state.ssid,password:$("wifiPassword").value})});$("wifiDialogMessage").textContent="Connection requested. Reopen vt-3dprinter.local:8080 if needed."}catch(err){$("wifiDialogMessage").textContent=err.message}};
$("forgetToken").onclick=()=>{sessionStorage.removeItem("vt_token");location.reload()};
$("loginForm").onsubmit=async e=>{e.preventDefault();state.token=$("tokenInput").value.trim();try{await api("/api/status");sessionStorage.setItem("vt_token",state.token);$("loginOverlay").classList.add("hidden");status()}catch{$("loginError").textContent="Access key not accepted."}};
(async()=>{if(state.token){try{await api("/api/status");$("loginOverlay").classList.add("hidden");status()}catch{}}setInterval(()=>{if(state.token)status().catch(()=>{})},10000)})();