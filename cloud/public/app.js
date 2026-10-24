const $=id=>document.getElementById(id);
const state={key:localStorage.getItem("vt_cloud_key")||"",device:null,health:null};

function pill(el,ok,text){
  el.textContent=text;
  el.className="pill "+(ok?"ok":"bad");
}
function lockBadge(el,unlocked){
  el.textContent=unlocked?"UNLOCKED":"LOCKED";
  el.className="lock-badge"+(unlocked?" ok":"");
}
async function json(path,opts={}){
  const headers={...(opts.headers||{})};
  if(state.key)headers["X-Cloud-Access-Key"]=state.key;
  if(opts.body)headers["Content-Type"]="application/json";
  const r=await fetch(path,{...opts,headers,cache:"no-store"});
  const raw=await r.text();
  let d={};
  try{d=raw?JSON.parse(raw):{}}catch{throw new Error(raw||("HTTP "+r.status))}
  if(!r.ok)throw new Error(d.detail||("HTTP "+r.status));
  return d;
}
async function proxy(path,opts={}){
  return json("/api/device/proxy"+path,opts);
}

async function refresh(){
  try{
    const health=await json("/api/health");
    const device=await json("/api/device/status");
    state.health=health;state.device=device;

    $("sidebarDot").classList.add("online");
    $("sidebarStatus").textContent="Cloud online";
    pill($("cloudBadge"),true,"CLOUD ONLINE");
    $("cloudState").textContent="ONLINE";
    $("cloudVersion").textContent="API v"+health.version;
    $("systemApiState").textContent="Online";

    $("piState").textContent=device.online?"ONLINE":(device.paired?"OFFLINE":"NOT PAIRED");
    $("piHost").textContent=device.hostname||"Not paired";
    $("printerState").textContent=device.printer_connected?"CONNECTED":"OFFLINE";
    $("cameraState").textContent=device.camera_connected?"CONNECTED":"OFFLINE";
    $("deviceId").textContent=device.device_id||"—";
    $("deviceHost").textContent=device.hostname||"—";
    $("pairMessage").textContent=device.message||"";
    $("systemDeviceState").textContent=device.online?"Online":(device.paired?"Offline":"Not paired");
    pill($("pairBadge"),device.online,device.online?"ONLINE":(device.paired?"OFFLINE":"NOT PAIRED"));

    if(device.online){
      $("heroStatus").textContent="Bioprinter connected";
      $("heroSub").textContent="The Raspberry Pi is reachable through the secure cloud bridge.";
      pill($("heroPill"),true,"DEVICE ONLINE");
      await Promise.allSettled([loadPrinter(),loadCamera()]);
    }else{
      $("heroStatus").textContent="Cloud dashboard online";
      $("heroSub").textContent=device.paired?"Raspberry Pi is paired but currently unreachable.":"Raspberry Pi pairing is the next step.";
      pill($("heroPill"),false,device.paired?"PI OFFLINE":"PI NOT PAIRED");
      setOfflinePanels();
    }
  }catch(err){
    $("sidebarDot").classList.remove("online");
    $("sidebarStatus").textContent="Cloud error";
    pill($("cloudBadge"),false,"ERROR");
    $("cloudState").textContent="ERROR";
    $("heroStatus").textContent="Cloud API unavailable";
    $("heroSub").textContent=err.message;
    pill($("heroPill"),false,"ERROR");
    $("systemApiState").textContent="Error";
  }
}

function setOfflinePanels(){
  pill($("printerConnectionBadge"),false,"OFFLINE");
  pill($("cameraBadge"),false,"OFFLINE");
  lockBadge($("motionBadge"),false);
  document.querySelectorAll(".jog-btn").forEach(b=>b.disabled=true);
  $("printerDetails").innerHTML='<div><span>Status</span><strong>Waiting for Pi pairing</strong></div>';
  $("cameraDetails").innerHTML='<div><span>Status</span><strong>Waiting for Pi pairing</strong></div>';
}

async function loadPrinter(){
  try{
    const p=await proxy("/api/printer/status");
    pill($("printerConnectionBadge"),p.connected,p.connected?"CONNECTED":"NOT CONNECTED");
    const rows=p.selected
      ?[["Device",p.selected.device],["Description",p.selected.description],["Motion",p.commissioning_locked?"Locked":"Enabled"]]
      :[["Device","—"],["Status","No printer detected"]];
    $("printerDetails").innerHTML=rows.map(x=>'<div><span>'+x[0]+'</span><strong>'+x[1]+'</strong></div>').join("");
    const unlocked=!p.commissioning_locked;
    lockBadge($("motionBadge"),unlocked);
    document.querySelectorAll(".jog-btn").forEach(b=>b.disabled=!unlocked);
  }catch(err){
    pill($("printerConnectionBadge"),false,"ERROR");
    $("printerDetails").innerHTML='<div><span>Error</span><strong>'+err.message+'</strong></div>';
  }
}

async function loadCamera(){
  try{
    const c=await proxy("/api/camera/status");
    pill($("cameraBadge"),c.usb_detected,c.usb_detected?"CONNECTED":"NOT CONNECTED");
    $("cameraDetails").innerHTML=[
      ["USB detected",c.usb_detected?"Yes":"No"],
      ["Model",c.model||"—"],
      ["Serial",c.serial_number||"—"],
      ["SDK",c.sdk_available?"Ready":"Unavailable"]
    ].map(x=>'<div><span>'+x[0]+'</span><strong>'+x[1]+'</strong></div>').join("");
    $("cameraPlaceholder").textContent=c.usb_detected?"D405 connected. Live remote relay will be enabled after pairing validation.":"D405 not detected.";
  }catch(err){
    pill($("cameraBadge"),false,"ERROR");
    $("cameraDetails").innerHTML='<div><span>Error</span><strong>'+err.message+'</strong></div>';
  }
}

async function safeCommand(command){
  try{
    const d=await proxy("/api/printer/command",{method:"POST",body:JSON.stringify({command})});
    $("terminal").textContent=">>> "+d.command+"\n"+(d.response||[]).join("\n");
  }catch(err){$("terminal").textContent="ERROR: "+err.message}
}

async function jog(axis,sign){
  try{
    const d=await proxy("/api/printer/jog",{method:"POST",body:JSON.stringify({axis,distance_mm:Number(sign),feed_mm_min:300})});
    $("motionLog").textContent="Jog complete: "+d.axis+" "+d.distance_mm+" mm";
  }catch(err){$("motionLog").textContent="ERROR: "+err.message}
}

function activatePage(page){
  document.querySelectorAll(".nav-btn,.page").forEach(x=>x.classList.remove("active"));
  document.querySelector('.nav-btn[data-page="'+page+'"]')?.classList.add("active");
  $("page-"+page)?.classList.add("active");
  $("pageTitle").textContent=page[0].toUpperCase()+page.slice(1);
}
document.querySelectorAll(".nav-btn").forEach(b=>b.onclick=()=>activatePage(b.dataset.page));
document.querySelectorAll(".safe-command").forEach(b=>b.onclick=()=>safeCommand(b.dataset.command));
document.querySelectorAll(".jog-btn").forEach(b=>b.onclick=()=>jog(b.dataset.axis,b.dataset.sign));
$("refreshAll").onclick=refresh;
$("loginForm").onsubmit=async e=>{
  e.preventDefault();
  state.key=$("tokenInput").value.trim();
  $("loginError").textContent="";
  try{
    await json("/api/auth/check");
    localStorage.setItem("vt_cloud_key",state.key);
    $("loginOverlay").classList.add("hidden");
    await refresh();
  }catch(err){$("loginError").textContent="Access key not accepted."}
};

(async()=>{
  if(state.key){
    try{
      await json("/api/auth/check");
      $("loginOverlay").classList.add("hidden");
    }catch{localStorage.removeItem("vt_cloud_key");state.key=""}
  }
  await refresh();
  setInterval(refresh,10000);
})();