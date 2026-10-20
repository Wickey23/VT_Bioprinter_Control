const $=id=>document.getElementById(id);
const state={
  token:localStorage.getItem("vt_token")||"",
  ssid:"",
  commissioning:null,
  depthObjectUrl:null,
  colorObjectUrl:null,
  liveCamera:false,
  liveGeneration:0
};

async function api(path,opts={}){
  const headers={...(opts.headers||{}),"X-Bioprinter-Token":state.token};
  if(opts.body) headers["Content-Type"]="application/json";
  const r=await fetch(path,{...opts,headers});
  const d=await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(d.detail||("HTTP "+r.status));
  return d;
}

function pill(el,ok,text){
  el.textContent=text;
  el.className="pill "+(ok?"ok":"bad");
}

function lockBadge(el,unlocked){
  el.textContent=unlocked?"UNLOCKED":"LOCKED";
  el.className="lock-badge"+(unlocked?" ok":"");
}

function esc(s){
  return String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
}

function uptime(s){
  if(s==null)return "—";
  const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);
  return [d?d+"d":"",h?h+"h":"",m+"m"].filter(Boolean).join(" ");
}

function meters(v){
  if(v==null)return "—";
  if(v<1)return (v*1000).toFixed(1)+" mm";
  return v.toFixed(3)+" m";
}

async function status(){
  const s=await api("/api/status");
  $("sidebarDot").classList.add("online");
  $("sidebarStatus").textContent="Controller online";
  $("piState").textContent="ONLINE";
  $("piHost").textContent=s.hostname;

  $("printerState").textContent=s.printer.connected?"CONNECTED":"NOT CONNECTED";
  $("printerDevice").textContent=s.printer.device||"Awaiting lab connection";

  $("cameraState").textContent=s.camera.usb_detected?"CONNECTED":"NOT CONNECTED";
  $("cameraModel").textContent=s.camera.model||(
    s.camera.usb_detected?"Intel RealSense USB detected":"Awaiting D405"
  );

  $("wifiState").textContent=s.network.ssid||"NOT CONNECTED";
  $("wifiIp").textContent=s.network.ip_address||"No IPv4";
  $("cpuTemp").textContent=s.cpu_temp_c==null?"—":s.cpu_temp_c+" °C";
  $("diskUsed").textContent=s.disk.used_gb+" / "+s.disk.total_gb+" GB";
  $("diskFree").textContent=s.disk.free_gb+" GB";
  $("diskBar").style.width=Math.min(100,s.disk.used_gb/s.disk.total_gb*100)+"%";

  const unlocked=!s.printer.commissioning_locked;
  lockBadge($("dashboardLockBadge"),unlocked);
  $("commissioningSummary").textContent=unlocked
    ?"Commissioning checklist is complete. Only 0.1 mm and 1.0 mm jog tests are enabled."
    :"Motion remains disabled until the physical commissioning checklist is complete.";

  $("heroStatus").textContent=s.printer.connected?"Printer link detected":"Host ready — printer not connected";
  $("heroSub").textContent=s.printer.connected
    ?(unlocked?"Creality serial link is live; commissioning jogs are enabled.":"Creality serial link is live; motion remains commissioning-locked.")
    :"Raspberry Pi services are online and waiting for the printer controller.";
  pill($("heroPill"),true,s.printer.connected?"PRINTER FOUND":"HOST READY");

  $("currentSsid").textContent=s.network.ssid||"Not connected";
  $("currentIp").textContent=s.network.ip_address||"—";
  $("currentSignal").textContent=s.network.hotspot_active?"Direct AP":(s.network.signal==null?"—":s.network.signal+"%");
  $("currentSecurity").textContent=s.network.security||"—";
  pill($("wifiBadge"),s.network.connected,s.network.hotspot_active?"HOTSPOT":(s.network.connected?"CONNECTED":"OFFLINE"));

  $("systemDetails").innerHTML=[
    ["Hostname",s.hostname],
    ["Uptime",uptime(s.uptime_seconds)],
    ["CPU temperature",s.cpu_temp_c==null?"—":s.cpu_temp_c+" °C"],
    ["Storage free",s.disk.free_gb+" GB"],
    ["Network mode",s.network.mode],
    ["IP address",s.network.ip_address||"—"]
  ].map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");
}

async function printer(){
  const p=await api("/api/printer/status");
  pill($("printerConnectionBadge"),p.connected,p.connected?"CONNECTED":"NOT CONNECTED");
  const rows=p.selected
    ?[["Device",p.selected.device],["Description",p.selected.description],["USB ID",(p.selected.vid||"—")+":"+(p.selected.pid||"—")]]
    :[["Device","—"],["Status","Waiting for Creality/CH340 USB connection"]];
  rows.push(["Motion",p.commissioning_locked?"Commissioning locked":"Tiny jog tests enabled"]);
  $("printerDetails").innerHTML=rows.map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");
}

async function loadCommissioning(){
  const c=await api("/api/commissioning");
  state.commissioning=c;
  document.querySelectorAll("#commissioningChecklist input[data-key]").forEach(input=>{
    input.checked=!!c[input.dataset.key];
  });
  lockBadge($("commissioningBadge"),c.unlocked);
  lockBadge($("motionBadge"),c.unlocked);
  document.querySelectorAll(".jog-btn").forEach(b=>b.disabled=!c.unlocked);
  $("commissioningMessage").textContent=c.unlocked
    ?"Motion gate is open for 0.1 mm and 1.0 mm X/Y/Z jogs only."
    :"Complete every checklist item to enable tiny jog tests.";
  return c;
}

async function saveCommissioning(){
  const payload={};
  document.querySelectorAll("#commissioningChecklist input[data-key]").forEach(input=>{
    payload[input.dataset.key]=input.checked;
  });
  const c=await api("/api/commissioning",{method:"POST",body:JSON.stringify(payload)});
  await loadCommissioning();
  await printer();
  await status();
  $("commissioningMessage").textContent=c.unlocked
    ?"Commissioning state saved. Tiny jog controls are now enabled."
    :"State saved. Motion remains locked until every item is confirmed.";
}

async function lockMotion(){
  const payload={
    motors_connected:false,
    endstops_verified:false,
    workspace_clear:false,
    main_power_ready:false,
    physical_stop_ready:false
  };
  await api("/api/commissioning",{method:"POST",body:JSON.stringify(payload)});
  await loadCommissioning();
  await printer();
  await status();
}

async function jog(axis,sign){
  const step=Number($("jogStep").value);
  const distance=step*Number(sign);
  $("motionLog").textContent="Sending "+axis+" "+distance+" mm…";
  try{
    const d=await api("/api/printer/jog",{
      method:"POST",
      body:JSON.stringify({axis,distance_mm:distance,feed_mm_min:300})
    });
    $("motionLog").textContent=[
      "Jog complete: "+d.axis+" "+d.distance_mm+" mm @ "+d.feed_mm_min+" mm/min",
      ...(d.response||[])
    ].join("\n");
  }catch(err){
    $("motionLog").textContent="ERROR: "+err.message;
  }
}

async function camera(){
  try{
    const c=await api("/api/camera/status");
    pill($("cameraBadge"),c.usb_detected,c.usb_detected?"CONNECTED":"NOT CONNECTED");
    const rows=[
      ["USB detected",c.usb_detected?"Yes":"No"],
      ["Model",c.model||"—"],
      ["Serial",c.serial_number||"—"],
      ["Firmware",c.firmware||"—"],
      ["RealSense SDK",c.sdk_available?"Ready":"Not installed / not importable"]
    ];
    if(c.usb_lines?.length) rows.push(["USB",c.usb_lines[0]]);
    $("cameraDetails").innerHTML=rows.map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");
    $("cameraMessage").textContent=c.usb_detected&&!c.sdk_available
      ?"D405 is visible over USB. Run bash install_realsense.sh on the Pi to enable depth frames and measurements."
      :c.usb_detected?"D405 hardware and RealSense SDK are ready.":"Connect the D405 to a blue USB 3 port on the Raspberry Pi.";
    $("measureDepth").disabled=!(c.usb_detected&&c.sdk_available);
    $("refreshDepthImage").disabled=!(c.usb_detected&&c.sdk_available);
    $("startLiveCamera").disabled=!(c.usb_detected&&c.sdk_available);

    if(c.live?.running){
      state.liveCamera=true;
      updateLiveControls(c.live);
      if(!$("colorImage").classList.contains("visible")) runLiveCameraLoop();
    }else{
      updateLiveControls(c.live||{running:false,fps:0});
    }
  }catch(err){
    pill($("cameraBadge"),false,"ERROR");
    $("cameraMessage").textContent=err.message;
  }
}

function updateLiveControls(s){
  const running=!!s.running;
  pill($("liveCameraBadge"),running,running?"LIVE":"STOPPED");
  $("startLiveCamera").disabled=running;
  $("stopLiveCamera").disabled=!running;
  const fps=Number(s.fps||0);
  $("liveCameraStats").textContent=(s.color_resolution||"640x480")+" · "+(fps?fps.toFixed(1)+" FPS":"target 15 FPS");
  if(s.error)$("cameraMessage").textContent="Live camera error: "+s.error;
}

async function syncLiveCameraStatus(){
  const s=await api("/api/camera/live/status");
  updateLiveControls(s);
  return s;
}

async function startLiveCamera(){
  $("cameraMessage").textContent="Starting D405 live view…";
  $("liveCameraBadge").textContent="STARTING";
  $("liveCameraBadge").className="pill";
  $("startLiveCamera").disabled=true;
  try{
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),12000);
    const headers={"X-Bioprinter-Token":state.token};
    const r=await fetch("/api/camera/live/start",{
      method:"POST",
      headers,
      signal:controller.signal
    });
    clearTimeout(timer);
    const s=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(s.detail||("HTTP "+r.status));
    state.liveCamera=true;
    updateLiveControls(s);
    $("cameraMessage").textContent=(s.stream||"D405 live")+" feed is running. Depth measurements now use the same camera pipeline.";
    runLiveCameraLoop();
  }catch(err){
    state.liveCamera=false;
    const msg=err.name==="AbortError"
      ?"Camera start timed out. Refresh Camera and try once more."
      :err.message;
    $("cameraMessage").textContent=msg;
    updateLiveControls({running:false,error:msg});
  }
}

async function stopLiveCamera(){
  state.liveCamera=false;
  state.liveGeneration++;
  try{
    const s=await api("/api/camera/live/stop",{method:"POST"});
    updateLiveControls(s);
  }catch(err){
    $("cameraMessage").textContent=err.message;
  }
  if(state.colorObjectUrl){
    URL.revokeObjectURL(state.colorObjectUrl);
    state.colorObjectUrl=null;
  }
  $("colorImage").classList.remove("visible");
  $("colorImage").removeAttribute("src");
  $("colorPlaceholder").style.display="";
  $("colorPlaceholder").textContent="Start the live feed to see the camera view.";
}

async function runLiveCameraLoop(){
  if(!state.liveCamera)return;
  const generation=++state.liveGeneration;
  let frames=0;

  while(state.liveCamera&&generation===state.liveGeneration){
    const started=performance.now();
    try{
      const r=await fetch("/api/camera/color.jpg?ts="+Date.now(),{
        headers:{"X-Bioprinter-Token":state.token},
        cache:"no-store"
      });
      if(!r.ok){
        const d=await r.json().catch(()=>({}));
        throw new Error(d.detail||("HTTP "+r.status));
      }
      const blob=await r.blob();
      const nextUrl=URL.createObjectURL(blob);
      const previous=state.colorObjectUrl;
      state.colorObjectUrl=nextUrl;
      $("colorImage").src=nextUrl;
      $("colorImage").classList.add("visible");
      $("colorPlaceholder").style.display="none";
      if(previous)URL.revokeObjectURL(previous);

      frames++;
      if(frames%10===0){
        syncLiveCameraStatus().catch(()=>{});
      }
    }catch(err){
      $("cameraMessage").textContent="Live feed error: "+err.message;
      await new Promise(resolve=>setTimeout(resolve,500));
    }

    const elapsed=performance.now()-started;
    const delay=Math.max(0,90-elapsed);
    if(delay)await new Promise(resolve=>setTimeout(resolve,delay));
  }
}

async function measureDepth(){
  $("cameraMessage").textContent="Capturing depth measurement…";
  try{
    const m=await api("/api/camera/measure");
    $("depthCenter").textContent=meters(m.center_distance_m);
    $("depthMedian").textContent=meters(m.roi_median_m);
    $("depthMin").textContent=meters(m.roi_min_m);
    $("depthMax").textContent=meters(m.roi_max_m);
    $("cameraMessage").textContent="Depth sample captured at "+m.width+"×"+m.height+".";
  }catch(err){
    $("cameraMessage").textContent=err.message;
  }
}

async function refreshDepthImage(){
  $("cameraMessage").textContent="Capturing depth frame…";
  try{
    const r=await fetch("/api/camera/depth.jpg?ts="+Date.now(),{
      headers:{"X-Bioprinter-Token":state.token},
      cache:"no-store"
    });
    if(!r.ok){
      const d=await r.json().catch(()=>({}));
      throw new Error(d.detail||("HTTP "+r.status));
    }
    const blob=await r.blob();
    if(state.depthObjectUrl) URL.revokeObjectURL(state.depthObjectUrl);
    state.depthObjectUrl=URL.createObjectURL(blob);
    $("depthImage").src=state.depthObjectUrl;
    $("depthImage").classList.add("visible");
    $("depthPlaceholder").style.display="none";
    $("cameraMessage").textContent="Depth visualization updated.";
  }catch(err){
    $("cameraMessage").textContent=err.message;
  }
}

async function hotspot(){
  const h=await api("/api/network/hotspot");
  $("hotspotSsid").textContent=h.ssid;
  $("hotspotPassword").textContent=h.password;
  $("hotspotUrl").textContent=h.url;
  pill($("hotspotBadge"),h.active,h.active?"ACTIVE":"READY");
  $("hotspotOn").disabled=h.active;
  $("hotspotOn").textContent=h.active?"Setup hotspot active":"Start setup hotspot";
}

function openWifi(ssid){
  state.ssid=ssid;
  $("dialogSsid").textContent=ssid;
  $("wifiPassword").value="";
  $("wifiDialogMessage").textContent="";
  $("wifiDialog").showModal();
}

async function scan(){
  $("wifiList").innerHTML='<p class="muted">Scanning…</p>';
  const d=await api("/api/network/scan");
  $("wifiList").innerHTML=d.networks.map(n=>
    '<div class="wifi-item"><div class="wifi-meta"><strong>'+esc(n.ssid)+(n.in_use?" ✓":"")+
    '</strong><small>'+esc(n.security)+" · Signal "+n.signal+
    '%</small></div><button class="secondary join" data-s="'+esc(n.ssid)+'">Connect</button></div>'
  ).join("")||'<p class="muted">No networks found. You can enter the SSID manually above.</p>';
  document.querySelectorAll(".join").forEach(b=>b.onclick=()=>openWifi(b.dataset.s));
}

async function saved(){
  const d=await api("/api/network/saved");
  $("savedNetworks").innerHTML=d.connections.map(n=>
    '<div class="saved-item"><span>'+esc(n)+'</span><button data-n="'+esc(n)+'">Forget</button></div>'
  ).join("")||'<p class="muted">No saved Wi-Fi profiles.</p>';
  $("savedNetworks").querySelectorAll("button").forEach(b=>b.onclick=async()=>{
    if(confirm("Forget "+b.dataset.n+"?")){
      await api("/api/network/forget",{method:"POST",body:JSON.stringify({connection:b.dataset.n})});
      saved();
    }
  });
}

function activatePage(page){
  const current=document.querySelector(".nav-btn.active")?.dataset.page;
  if(current==="camera"&&page!=="camera"&&state.liveCamera){
    stopLiveCamera().catch(()=>{});
  }
  document.querySelectorAll(".nav-btn,.page").forEach(x=>x.classList.remove("active"));
  const nav=document.querySelector('.nav-btn[data-page="'+page+'"]');
  if(nav)nav.classList.add("active");
  $("page-"+page).classList.add("active");
  $("pageTitle").textContent=page[0].toUpperCase()+page.slice(1);
  if(page==="network"){saved().catch(()=>{});hotspot().catch(()=>{})}
  if(page==="printer"){printer().catch(()=>{});loadCommissioning().catch(()=>{})}
  if(page==="camera"){camera().catch(()=>{})}
}

document.querySelectorAll(".nav-btn").forEach(b=>b.onclick=()=>activatePage(b.dataset.page));
document.querySelectorAll(".nav-jump").forEach(b=>b.onclick=()=>activatePage(b.dataset.target));

document.querySelectorAll(".safe-command").forEach(b=>b.onclick=async()=>{
  try{
    const d=await api("/api/printer/command",{method:"POST",body:JSON.stringify({command:b.dataset.command})});
    $("terminal").textContent=">>> "+d.command+"\n"+d.response.join("\n");
  }catch(e){
    $("terminal").textContent="ERROR: "+e.message;
  }
});

document.querySelectorAll(".jog-btn").forEach(b=>b.onclick=()=>jog(b.dataset.axis,b.dataset.sign));

$("saveCommissioning").onclick=()=>saveCommissioning().catch(e=>$("commissioningMessage").textContent=e.message);
$("lockMotion").onclick=()=>lockMotion().catch(e=>$("commissioningMessage").textContent=e.message);

$("emergencyStop").onclick=async()=>{
  if(!confirm("Send Marlin M112 emergency stop now?"))return;
  try{
    const d=await api("/api/printer/emergency-stop",{method:"POST"});
    $("motionLog").textContent=d.message;
  }catch(err){
    $("motionLog").textContent="ERROR: "+err.message;
  }
};

$("refreshCamera").onclick=()=>camera();
$("measureDepth").onclick=()=>measureDepth();
$("refreshDepthImage").onclick=()=>refreshDepthImage();
$("startLiveCamera").onclick=()=>startLiveCamera();
$("stopLiveCamera").onclick=()=>stopLiveCamera();

$("scanWifi").onclick=()=>scan().catch(e=>$("wifiList").innerHTML='<p class="error">'+esc(e.message)+'</p>');
$("manualConnect").onclick=()=>{
  const ssid=$("manualSsid").value.trim();
  if(!ssid){$("manualSsid").focus();return}
  openWifi(ssid);
};

$("refreshPrinter").onclick=()=>printer();
$("refreshAll").onclick=()=>{
  status().catch(()=>{});
  printer().catch(()=>{});
  camera().catch(()=>{});
  hotspot().catch(()=>{});
};

$("cancelWifi").onclick=()=>$("wifiDialog").close();

$("wifiForm").onsubmit=async e=>{
  e.preventDefault();
  $("wifiDialogMessage").textContent="Changing network… this page may disconnect.";
  try{
    await api("/api/network/connect",{method:"POST",body:JSON.stringify({ssid:state.ssid,password:$("wifiPassword").value})});
    $("wifiDialogMessage").textContent="Connection requested. Reopen vt-3dprinter.local:8080 on the new network.";
  }catch(err){
    if(String(err.message).includes("Failed to fetch")){
      $("wifiDialogMessage").textContent="The Pi changed networks. Reconnect your device to the new network, then open vt-3dprinter.local:8080.";
    }else{
      $("wifiDialogMessage").textContent=err.message;
    }
  }
};

$("hotspotOn").onclick=async()=>{
  if(!confirm("Start VT-Bioprinter-Setup? Your current Wi-Fi connection to the Pi will drop."))return;
  $("hotspotMessage").textContent="Starting setup hotspot…";
  try{await api("/api/network/hotspot/enable",{method:"POST"});}catch(_){}
  $("hotspotMessage").textContent="Connect to VT-Bioprinter-Setup (password: bioprinter), then open http://10.42.0.1:8080";
};

$("forgetToken").onclick=()=>{
  localStorage.removeItem("vt_token");
  location.reload();
};

$("loginForm").onsubmit=async e=>{
  e.preventDefault();
  state.token=$("tokenInput").value.trim();
  try{
    await api("/api/status");
    localStorage.setItem("vt_token",state.token);
    $("loginOverlay").classList.add("hidden");
    await Promise.allSettled([status(),printer(),camera(),loadCommissioning()]);
  }catch{
    $("loginError").textContent="Access key not accepted.";
  }
};

(async()=>{
  if(state.token){
    try{
      await api("/api/status");
      $("loginOverlay").classList.add("hidden");
      await Promise.allSettled([status(),printer(),camera(),loadCommissioning()]);
    }catch{}
  }
  setInterval(()=>{if(state.token)status().catch(()=>{})},10000);
})();


window.startLiveCamera=startLiveCamera;
window.stopLiveCamera=stopLiveCamera;
