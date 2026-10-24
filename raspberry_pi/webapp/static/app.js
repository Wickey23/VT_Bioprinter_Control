const $=id=>document.getElementById(id);
const state={
  token:localStorage.getItem("vt_token")||"",
  ssid:"",
  commissioning:null,
  depthObjectUrl:null,
  colorObjectUrl:null,
  liveCamera:false,
  liveGeneration:0,
  calibrationProfile:null,
  calibrationPoints:[],
  calibrationMode:"bed",
  calibrationObjectUrl:null,
  calibrationSurface:null,
  monitorActive:false,
  monitorGeneration:0,
  monitorObjectUrl:null,
  monitorSurface:null,
  planSummary:null,
  projectedPlan:null,
  activeExperiment:null,
  printerPosition:null,
  printerProjectedPixel:null,
  trackedNozzle:null,
  qualityResult:null,
  qualityObjectUrl:null,
  slicedGcode:null,
  slicedFilename:null,
  slicerPreflightReady:false,
  printState:null,
  printCameraActive:false,
  printCameraGeneration:0,
  printCameraObjectUrl:null
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

  $("dashboardCalibration").textContent=s.research?.calibrated?"VALID":"NOT SET";
  $("dashboardBaseline").textContent=s.research?.surface_baseline?"Reference surface saved":"No surface baseline";
  $("dashboardPlan").textContent=s.research?.plan_loaded?"LOADED":"NONE";
  $("dashboardPlanFile").textContent=s.research?.plan_filename||"No G-code plan";
  $("dashboardExperiment").textContent=s.research?.experiment_active?"RECORDING":"IDLE";
  $("dashboardExperimentName").textContent=s.research?.experiment_name||"No active session";
  $("dashboardMode").textContent=s.research?.mode||"OBSERVE";

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
  rows.push(["Motion",p.commissioning_locked?"Commissioning locked":"Jog controls enabled"]);
  rows.push(["Homed reference",p.motion_reference?.homed?"Known":"Not established"]);
  if(p.limits_mm){
    rows.push(["Software limits","X 0–220 · Y 0–220 · Z 0–250 mm"]);
  }
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
  $("homeCenter").disabled=!c.unlocked;
  $("commissioningMessage").textContent=c.unlocked
    ?"Motion gate is open. Home + Center establishes the reference required for 5/10/25 mm jogs and software travel limits."
    :"Complete every checklist item to enable motion.";
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
    ?"Commissioning state saved. Motion controls are enabled; use Home + Center before large jogs."
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

async function homeCenter(){
  if(!confirm("Home X/Y/Z, lift to Z=10 mm, then move X/Y to bed center (110,110)? Keep the physical power switch within reach."))return;
  $("motionLog").textContent="Homing on verified endstops, then moving to center…";
  $("homeCenter").disabled=true;
  document.querySelectorAll(".jog-btn").forEach(b=>b.disabled=true);
  try{
    const d=await api("/api/printer/home-center",{method:"POST"});
    const p=d.position_mm||{};
    $("motionLog").textContent=[
      "Home + Center complete.",
      "Position: X "+(p.x??"—")+" · Y "+(p.y??"—")+" · Z "+(p.z??"—")+" mm",
      "Large jog protection is now active for X 0–220, Y 0–220, Z 0–250 mm.",
      ...(d.response||[])
    ].join("\n");
    await printer();
  }catch(err){
    $("motionLog").textContent="ERROR: "+err.message;
  }finally{
    if(state.commissioning?.unlocked){
      $("homeCenter").disabled=false;
      document.querySelectorAll(".jog-btn").forEach(b=>b.disabled=false);
    }
  }
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
    const after=d.position_after_mm;
    $("motionLog").textContent=[
      "Jog complete: "+d.axis+" "+d.distance_mm+" mm @ "+d.feed_mm_min+" mm/min",
      d.homed_reference&&after
        ?("Position: X "+after.x+" · Y "+after.y+" · Z "+after.z+" mm")
        :"Position reference: not homed by this controller session",
      "Endstops: "+JSON.stringify(d.endstops||{}),
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


function canvasPoint(event,canvas){
  const rect=canvas.getBoundingClientRect();
  return {
    u:(event.clientX-rect.left)/rect.width*canvas.width,
    v:(event.clientY-rect.top)/rect.height*canvas.height
  };
}

function drawMarker(ctx,u,v,label,fill="#fff"){
  ctx.beginPath();
  ctx.arc(u,v,7,0,Math.PI*2);
  ctx.fillStyle=fill;
  ctx.fill();
  ctx.lineWidth=2;
  ctx.strokeStyle="#0b1220";
  ctx.stroke();
  ctx.font="bold 14px system-ui";
  ctx.fillStyle=fill;
  ctx.strokeStyle="#0b1220";
  ctx.lineWidth=4;
  ctx.strokeText(label,u+10,v-10);
  ctx.fillText(label,u+10,v-10);
}

function zColor(z){
  const a=Math.abs(Number(z)||0);
  if(a<=0.25)return "#22c55e";
  if(a<=0.75)return "#eab308";
  return "#ef4444";
}

function drawBedOverlay(canvas,profile,surface,nozzleOverride=null){
  if(!canvas||!canvas.width||!canvas.height)return;
  const ctx=canvas.getContext("2d");
  ctx.clearRect(0,0,canvas.width,canvas.height);

  const corners=profile?.bed?.corners||[];
  if(corners.length===4){
    ctx.beginPath();
    ctx.moveTo(corners[0].u,corners[0].v);
    for(let i=1;i<4;i++)ctx.lineTo(corners[i].u,corners[i].v);
    ctx.closePath();
    ctx.lineWidth=3;
    ctx.strokeStyle="#22c55e";
    ctx.stroke();
    const labels=["FL","FR","RR","RL"];
    corners.forEach((p,i)=>drawMarker(ctx,p.u,p.v,labels[i],"#22c55e"));
  }

  const nozzle=nozzleOverride||profile?.nozzle_reference;
  if(nozzle?.pixel){
    drawMarker(ctx,nozzle.pixel[0],nozzle.pixel[1],"NOZZLE","#e87722");
  }

  if(surface?.samples){
    for(const point of surface.samples){
      ctx.beginPath();
      ctx.arc(point.u,point.v,4,0,Math.PI*2);
      ctx.fillStyle=zColor(point.delta_z_mm??point.z_mm);
      ctx.globalAlpha=.8;
      ctx.fill();
      ctx.globalAlpha=1;
    }
  }
}

function drawCalibrationOverlay(){
  const canvas=$("calibrationCanvas");
  if(!canvas)return;
  const ctx=canvas.getContext("2d");
  ctx.clearRect(0,0,canvas.width,canvas.height);

  const points=state.calibrationPoints;
  if(points.length){
    if(points.length>1){
      ctx.beginPath();
      ctx.moveTo(points[0].u,points[0].v);
      for(let i=1;i<points.length;i++)ctx.lineTo(points[i].u,points[i].v);
      if(points.length===4)ctx.closePath();
      ctx.lineWidth=3;
      ctx.strokeStyle="#22c55e";
      ctx.stroke();
    }
    const labels=["1 FL","2 FR","3 RR","4 RL"];
    points.forEach((point,index)=>drawMarker(ctx,point.u,point.v,labels[index],"#22c55e"));
  }

  const nozzle=state.calibrationProfile?.nozzle_reference;
  if(nozzle?.pixel){
    drawMarker(ctx,nozzle.pixel[0],nozzle.pixel[1],"NOZZLE","#e87722");
  }

  if(state.calibrationSurface?.samples){
    for(const point of state.calibrationSurface.samples){
      ctx.beginPath();
      ctx.arc(point.u,point.v,4,0,Math.PI*2);
      ctx.fillStyle=zColor(point.delta_z_mm??point.z_mm);
      ctx.globalAlpha=.8;
      ctx.fill();
      ctx.globalAlpha=1;
    }
  }
}

function updateCalibrationPointList(){
  const names=["Front-left","Front-right","Rear-right","Rear-left"];
  $("calibrationPointStatus").textContent=state.calibrationPoints.length+" / 4 POINTS";
  $("solveCalibration").disabled=state.calibrationPoints.length!==4;
  $("calibrationPointList").innerHTML=state.calibrationPoints.map((p,i)=>
    '<div class="calibration-point"><strong>'+names[i]+'</strong>'+
    'Pixel '+p.u.toFixed(1)+', '+p.v.toFixed(1)+'<br>'+
    'Depth '+meters(p.depth_m)+'</div>'
  ).join("");
}

function renderCalibrationProfile(profile){
  state.calibrationProfile=profile||null;
  const valid=!!profile;
  pill($("calibrationBadge"),valid,valid?"CALIBRATED":"NOT CALIBRATED");
  $("markNozzleTip").disabled=!valid;
  $("analyzeCalibrationSurface").disabled=!valid;
  $("saveSurfaceBaseline").disabled=!(valid&&state.calibrationSurface);
  $("monitorSurfaceScan").disabled=!valid;

  if(!valid){
    $("calibrationDetails").innerHTML='<div><span>Status</span><strong>No saved profile</strong></div>';
    pill($("nozzleBadge"),false,"NOT SET");
    $("nozzleDetails").innerHTML="";
    $("calibrationMessage").textContent="Capture a camera frame, then click the four bed corners in printer-coordinate order.";
    renderMonitorCalibration();
    updateAnalyticsReadiness();
    return;
  }

  const rms=profile.camera_to_printer?.rms_corner_error_mm;
  $("calibrationDetails").innerHTML=[
    ["Camera",profile.camera?.model||"D405"],
    ["Serial",profile.camera?.serial||"—"],
    ["Bed",Number(profile.bed?.width_mm).toFixed(1)+" × "+Number(profile.bed?.depth_mm).toFixed(1)+" mm"],
    ["Corner-fit RMS",rms==null?"—":Number(rms).toFixed(3)+" mm"],
    ["Transform",profile.camera_to_printer?.method||"—"],
    ["Surface baseline",profile.surface_baseline?"Saved":"Not saved"]
  ].map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");

  $("calOriginX").value=profile.bed?.origin_x_mm??0;
  $("calOriginY").value=profile.bed?.origin_y_mm??0;
  $("calBedWidth").value=profile.bed?.width_mm??220;
  $("calBedDepth").value=profile.bed?.depth_mm??220;

  if(profile.nozzle_reference){
    pill($("nozzleBadge"),true,"SET");
    const xyz=profile.nozzle_reference.printer_xyz_mm;
    $("nozzleDetails").innerHTML=[
      ["X",xyz[0].toFixed(3)+" mm"],
      ["Y",xyz[1].toFixed(3)+" mm"],
      ["Z",xyz[2].toFixed(3)+" mm"]
    ].map(x=>"<div><span>"+x[0]+"</span><strong>"+x[1]+"</strong></div>").join("");
  }else{
    pill($("nozzleBadge"),false,"NOT SET");
    $("nozzleDetails").innerHTML='<div><span>Status</span><strong>Mark nozzle after bed calibration</strong></div>';
  }

  $("calibrationMessage").textContent="Calibration is saved. Keep the D405 rigidly mounted; moving the camera invalidates this transform.";
  renderMonitorCalibration();
  updateAnalyticsReadiness();
}

async function loadCalibration(){
  const d=await api("/api/calibration");
  renderCalibrationProfile(d.profile);
  if(d.profile?.bed?.corners?.length===4 && state.calibrationPoints.length===0){
    state.calibrationPoints=d.profile.bed.corners.map(p=>({...p}));
    updateCalibrationPointList();
    drawCalibrationOverlay();
  }
  return d.profile;
}

async function ensureCalibrationCamera(){
  const s=await api("/api/camera/live/status");
  if(!s.running){
    const started=await api("/api/camera/live/start",{method:"POST"});
    if(started.error)throw new Error(started.error);
  }
}

async function fetchCameraBlob(path){
  const r=await fetch(path+"?ts="+Date.now(),{
    headers:{"X-Bioprinter-Token":state.token},
    cache:"no-store"
  });
  if(!r.ok){
    const d=await r.json().catch(()=>({}));
    throw new Error(d.detail||("HTTP "+r.status));
  }
  return await r.blob();
}

async function captureCalibrationFrame(){
  $("calibrationMessage").textContent="Starting D405 and capturing a calibration frame…";
  try{
    await ensureCalibrationCamera();
    const blob=await fetchCameraBlob("/api/camera/color.jpg");
    if(state.calibrationObjectUrl)URL.revokeObjectURL(state.calibrationObjectUrl);
    state.calibrationObjectUrl=URL.createObjectURL(blob);
    const img=$("calibrationImage");
    img.onload=()=>{
      const canvas=$("calibrationCanvas");
      canvas.width=img.naturalWidth;
      canvas.height=img.naturalHeight;
      $("calibrationStage").classList.add("has-image");
      drawCalibrationOverlay();
    };
    img.src=state.calibrationObjectUrl;
    $("calibrationMessage").textContent=state.calibrationMode==="nozzle"
      ?"Click the visible nozzle/syringe tip."
      :"Click the four bed corners in order: front-left, front-right, rear-right, rear-left.";
  }catch(err){
    $("calibrationMessage").textContent="Calibration camera error: "+err.message;
  }
}

async function calibrationCanvasClick(event){
  const canvas=$("calibrationCanvas");
  if(!canvas.width)return;
  const point=canvasPoint(event,canvas);

  if(state.calibrationMode==="nozzle"){
    $("calibrationMessage").textContent="Measuring nozzle tip…";
    try{
      const d=await api("/api/calibration/nozzle",{
        method:"POST",
        body:JSON.stringify(point)
      });
      state.calibrationMode="bed";
      renderCalibrationProfile(d.profile);
      drawCalibrationOverlay();
      $("calibrationMessage").textContent="Nozzle reference saved in printer coordinates.";
    }catch(err){
      $("calibrationMessage").textContent="Nozzle reference failed: "+err.message;
    }
    return;
  }

  if(state.calibrationPoints.length>=4)return;
  $("calibrationMessage").textContent="Sampling depth at selected bed corner…";
  try{
    const sample=await api("/api/camera/pixel",{
      method:"POST",
      body:JSON.stringify(point)
    });
    state.calibrationPoints.push({
      u:sample.u,
      v:sample.v,
      depth_m:sample.depth_m,
      camera_xyz_m:sample.camera_xyz_m
    });
    state.calibrationSurface=null;
    updateCalibrationPointList();
    drawCalibrationOverlay();
    const left=4-state.calibrationPoints.length;
    $("calibrationMessage").textContent=left
      ?left+" bed corner"+(left===1?"":"s")+" remaining."
      :"All four corners captured. Verify bed dimensions, then solve calibration.";
  }catch(err){
    $("calibrationMessage").textContent="Point rejected: "+err.message;
  }
}

async function solveCalibration(){
  if(state.calibrationPoints.length!==4)return;
  const img=$("calibrationImage");
  const payload={
    points:state.calibrationPoints,
    origin_x_mm:Number($("calOriginX").value),
    origin_y_mm:Number($("calOriginY").value),
    width_mm:Number($("calBedWidth").value),
    depth_mm:Number($("calBedDepth").value),
    frame_width:img.naturalWidth||$("calibrationCanvas").width,
    frame_height:img.naturalHeight||$("calibrationCanvas").height
  };

  $("calibrationMessage").textContent="Solving camera-to-printer 3D transform…";
  try{
    const d=await api("/api/calibration/solve",{
      method:"POST",
      body:JSON.stringify(payload)
    });
    renderCalibrationProfile(d.profile);
    drawCalibrationOverlay();
    $("calibrationMessage").textContent="Calibration solved and saved. RMS corner error: "+
      Number(d.profile.camera_to_printer.rms_corner_error_mm).toFixed(3)+" mm.";
    if(state.planSummary)loadProjectedPlan().catch(()=>{});
  }catch(err){
    $("calibrationMessage").textContent="Calibration failed: "+err.message;
  }
}

async function clearCalibration(){
  if(!confirm("Clear the saved camera-to-printer calibration?"))return;
  await api("/api/calibration",{method:"DELETE"});
  state.calibrationProfile=null;
  state.calibrationPoints=[];
  state.calibrationSurface=null;
  state.calibrationMode="bed";
  updateCalibrationPointList();
  drawCalibrationOverlay();
  renderCalibrationProfile(null);
}

function resetCalibrationPoints(){
  state.calibrationPoints=[];
  state.calibrationSurface=null;
  state.calibrationMode="bed";
  updateCalibrationPointList();
  drawCalibrationOverlay();
  $("calibrationMessage").textContent="Points reset. Click front-left, front-right, rear-right, then rear-left.";
}

function beginNozzleMark(){
  if(!state.calibrationProfile)return;
  state.calibrationMode="nozzle";
  $("calibrationMessage").textContent="Nozzle-mark mode enabled. Capture a fresh frame if needed, then click the visible tip.";
}

function renderSurfaceMetrics(targetId,data){
  const el=$(targetId);
  if(!el)return;
  if(!data){
    el.innerHTML="";
    return;
  }
  const rows=[
    ["Samples",data.sample_count],
    ["Mean Z",Number(data.mean_z_mm).toFixed(3)+" mm"],
    ["RMS Z",Number(data.rms_z_mm).toFixed(3)+" mm"],
    ["Peak-to-peak",Number(data.peak_to_peak_mm).toFixed(3)+" mm"]
  ];
  if(data.deposition){
    rows.push(
      ["Mean ΔZ",Number(data.deposition.mean_delta_z_mm).toFixed(3)+" mm"],
      ["Max ΔZ",Number(data.deposition.max_delta_z_mm).toFixed(3)+" mm"],
      ["Positive samples",data.deposition.positive_sample_count]
    );
  }
  el.innerHTML=rows.map(x=>'<div><span>'+x[0]+'</span><strong>'+x[1]+'</strong></div>').join("");
}

async function saveCalibrationSurfaceBaseline(){
  if(!state.calibrationProfile)return;
  $("calibrationMessage").textContent="Capturing clean reference surface baseline…";
  $("saveSurfaceBaseline").disabled=true;
  try{
    const d=await api("/api/calibration/baseline",{
      method:"POST",
      body:JSON.stringify({columns:14,rows:10})
    });
    state.calibrationSurface=d.surface;
    renderCalibrationProfile(d.profile);
    renderSurfaceMetrics("surfaceMetrics",d.surface);
    drawCalibrationOverlay();
    pill($("surfaceBadge"),true,"BASELINE SAVED");
    $("calibrationMessage").textContent="Reference surface saved. Future scans can report deposition height relative to this baseline.";
  }catch(err){
    $("calibrationMessage").textContent="Unable to save reference surface: "+err.message;
    $("saveSurfaceBaseline").disabled=false;
  }
}

async function analyzeCalibrationSurface(){
  $("calibrationMessage").textContent="Sampling calibrated bed surface…";
  try{
    const d=await api("/api/calibration/surface",{
      method:"POST",
      body:JSON.stringify({columns:14,rows:10})
    });
    state.calibrationSurface=d;
    renderSurfaceMetrics("surfaceMetrics",d);
    pill($("surfaceBadge"),true,"SCANNED");
    drawCalibrationOverlay();
    $("saveSurfaceBaseline").disabled=false;
    $("calibrationMessage").textContent=d.deposition
      ?"Surface map captured and compared with the saved baseline. Overlay color uses deposition ΔZ."
      :"Surface map captured. Green points are near Z=0; yellow/red indicate larger deviation.";
  }catch(err){
    pill($("surfaceBadge"),false,"ERROR");
    $("calibrationMessage").textContent="Surface analysis failed: "+err.message;
  }
}

function renderMonitorCalibration(){
  const profile=state.calibrationProfile;
  const target=$("monitorCalibrationDetails");
  if(!target)return;
  if(!profile){
    target.innerHTML='<div><span>Status</span><strong>Calibration required</strong></div>';
    $("monitorSurfaceScan").disabled=true;
    return;
  }

  target.innerHTML=[
    ["Status","VALID"],
    ["RMS corner error",Number(profile.camera_to_printer?.rms_corner_error_mm||0).toFixed(3)+" mm"],
    ["Bed",Number(profile.bed.width_mm).toFixed(1)+" × "+Number(profile.bed.depth_mm).toFixed(1)+" mm"],
    ["Nozzle",profile.nozzle_reference?"Referenced":"Not marked"],
    ["Surface baseline",profile.surface_baseline?"Saved":"Not saved"]
  ].map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");
  $("monitorSurfaceScan").disabled=false;
}

function setupCanvasForImage(img,canvas){
  if(!img.naturalWidth||!img.naturalHeight)return;
  if(canvas.width!==img.naturalWidth||canvas.height!==img.naturalHeight){
    canvas.width=img.naturalWidth;
    canvas.height=img.naturalHeight;
  }
}

function drawMonitorOverlay(){
  const canvas=$("monitorCanvas");
  setupCanvasForImage($("monitorImage"),canvas);
  drawBedOverlay(canvas,state.calibrationProfile,state.monitorSurface);

  if(state.projectedPlan?.segments?.length){
    const ctx=canvas.getContext("2d");
    ctx.save();
    ctx.strokeStyle="#38bdf8";
    ctx.lineWidth=2;
    ctx.globalAlpha=.65;
    ctx.beginPath();
    for(const segment of state.projectedPlan.segments){
      ctx.moveTo(segment.start[0],segment.start[1]);
      ctx.lineTo(segment.end[0],segment.end[1]);
    }
    ctx.stroke();
    ctx.restore();
  }

  if(state.printerProjectedPixel){
    const ctx=canvas.getContext("2d");
    drawMarker(ctx,state.printerProjectedPixel[0],state.printerProjectedPixel[1],"M114","#a78bfa");
  }

  if(state.trackedNozzle){
    const ctx=canvas.getContext("2d");
    const pct=Math.round(Number(state.trackedNozzle.confidence||0)*100);
    drawMarker(ctx,state.trackedNozzle.u,state.trackedNozzle.v,"VISION "+pct+"%","#f59e0b");
  }
}

async function refreshPrinterPosition(){
  try{
    const d=await api("/api/monitor/printer-position");
    state.printerPosition=d.position_mm;
    state.printerProjectedPixel=d.projected_pixel||null;
    const p=d.position_mm;
    $("monitorPrinterDetails").innerHTML=[
      ["X",Number(p.x).toFixed(3)+" mm"],
      ["Y",Number(p.y).toFixed(3)+" mm"],
      ["Z",Number(p.z).toFixed(3)+" mm"],
      ["Projected",d.projected_pixel?"Visible in camera":"Not projected"]
    ].map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");
    drawMonitorOverlay();
    return d;
  }catch(err){
    state.printerProjectedPixel=null;
    $("monitorPrinterDetails").innerHTML='<div><span>Status</span><strong>'+esc(err.message)+'</strong></div>';
    return null;
  }
}

async function refreshNozzleTracking(){
  if(!state.calibrationProfile?.nozzle_reference?.vision_template){
    state.trackedNozzle=null;
    $("monitorNozzleTrackDetails").innerHTML='<div><span>Status</span><strong>Re-mark nozzle in Calibration</strong></div>';
    return null;
  }

  try{
    const d=await api("/api/monitor/nozzle-track");
    const t=d.tracked;
    state.trackedNozzle=t;
    const xyz=t.printer_xyz_mm||[];
    $("monitorNozzleTrackDetails").innerHTML=[
      ["Confidence",Math.round(Number(t.confidence||0)*100)+"%"],
      ["Correlation",Number(t.correlation||0).toFixed(3)],
      ["X",xyz.length?Number(xyz[0]).toFixed(2)+" mm":"—"],
      ["Y",xyz.length?Number(xyz[1]).toFixed(2)+" mm":"—"],
      ["Z",xyz.length?Number(xyz[2]).toFixed(2)+" mm":"—"],
      ["Recovery",t.recovered_full_frame?"Full-frame search":"Local search"]
    ].map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");
    drawMonitorOverlay();
    return d;
  }catch(err){
    state.trackedNozzle=null;
    $("monitorNozzleTrackDetails").innerHTML='<div><span>Status</span><strong>'+esc(err.message)+'</strong></div>';
    return null;
  }
}

async function startMonitor(){
  $("monitorMessage").textContent="Starting calibrated camera monitor…";
  try{
    await ensureCalibrationCamera();
    state.monitorActive=true;
    state.monitorGeneration++;
    pill($("monitorCameraBadge"),true,"LIVE");
    $("startMonitor").disabled=true;
    $("stopMonitor").disabled=false;
    $("monitorPlaceholder").style.display="none";
    monitorLoop(state.monitorGeneration);
    refreshPrinterPosition().catch(()=>{});
    refreshNozzleTracking().catch(()=>{});
    $("monitorMessage").textContent=state.calibrationProfile
      ?"Observe mode active. Click the image to query printer X/Y/Z."
      :"Camera is live, but calibration is required for printer coordinates.";
  }catch(err){
    state.monitorActive=false;
    pill($("monitorCameraBadge"),false,"ERROR");
    $("monitorMessage").textContent=err.message;
  }
}

async function stopMonitor(){
  state.monitorActive=false;
  state.monitorGeneration++;
  try{await api("/api/camera/live/stop",{method:"POST"});}catch(_){}
  pill($("monitorCameraBadge"),false,"STOPPED");
  $("startMonitor").disabled=false;
  $("stopMonitor").disabled=true;
  if(state.monitorObjectUrl){
    URL.revokeObjectURL(state.monitorObjectUrl);
    state.monitorObjectUrl=null;
  }
  $("monitorImage").removeAttribute("src");
  $("monitorPlaceholder").style.display="";
  $("monitorPlaceholder").textContent="Start the monitor to view calibrated printer coordinates.";
  state.printerProjectedPixel=null;
  state.trackedNozzle=null;
}

async function monitorLoop(generation){
  let frameCounter=0;
  while(state.monitorActive&&generation===state.monitorGeneration){
    const started=performance.now();
    try{
      const blob=await fetchCameraBlob("/api/camera/color.jpg");
      const url=URL.createObjectURL(blob);
      const old=state.monitorObjectUrl;
      state.monitorObjectUrl=url;
      const img=$("monitorImage");
      img.onload=()=>{
        setupCanvasForImage(img,$("monitorCanvas"));
        drawMonitorOverlay();
      };
      img.src=url;
      if(old)URL.revokeObjectURL(old);

      frameCounter++;
      if(frameCounter%10===0){
        refreshPrinterPosition().catch(()=>{});
      }
      if(frameCounter%15===0){
        refreshNozzleTracking().catch(()=>{});
      }
    }catch(err){
      $("monitorMessage").textContent="Monitor frame error: "+err.message;
      await new Promise(resolve=>setTimeout(resolve,500));
    }
    const delay=Math.max(0,120-(performance.now()-started));
    if(delay)await new Promise(resolve=>setTimeout(resolve,delay));
  }
}

async function monitorCanvasClick(event){
  if(!state.monitorActive)return;
  const canvas=$("monitorCanvas");
  const point=canvasPoint(event,canvas);
  $("monitorMessage").textContent="Sampling 3D point…";
  try{
    const d=await api("/api/camera/pixel",{
      method:"POST",
      body:JSON.stringify(point)
    });
    $("monitorDepth").textContent=meters(d.depth_m);
    if(d.printer_xyz_mm){
      $("monitorX").textContent=Number(d.printer_xyz_mm[0]).toFixed(2)+" mm";
      $("monitorY").textContent=Number(d.printer_xyz_mm[1]).toFixed(2)+" mm";
      $("monitorZ").textContent=Number(d.printer_xyz_mm[2]).toFixed(2)+" mm";
      $("monitorMessage").textContent="Point converted from D405 depth into printer coordinates.";
    }else{
      $("monitorX").textContent="—";
      $("monitorY").textContent="—";
      $("monitorZ").textContent="—";
      $("monitorMessage").textContent="Depth measured, but camera-to-printer calibration is not available.";
    }
  }catch(err){
    $("monitorMessage").textContent="Coordinate sample failed: "+err.message;
  }
}

async function analyzeMonitorSurface(){
  $("monitorMessage").textContent="Scanning calibrated surface…";
  try{
    const d=await api("/api/calibration/surface",{
      method:"POST",
      body:JSON.stringify({columns:14,rows:10})
    });
    state.monitorSurface=d;
    $("monitorSurfaceDetails").innerHTML=[
      ["Samples",d.sample_count],
      ["Mean Z",Number(d.mean_z_mm).toFixed(3)+" mm"],
      ["RMS Z",Number(d.rms_z_mm).toFixed(3)+" mm"],
      ["Minimum",Number(d.min_z_mm).toFixed(3)+" mm"],
      ["Maximum",Number(d.max_z_mm).toFixed(3)+" mm"],
      ["Peak-to-peak",Number(d.peak_to_peak_mm).toFixed(3)+" mm"],
      ...(d.deposition?[
        ["Mean deposition ΔZ",Number(d.deposition.mean_delta_z_mm).toFixed(3)+" mm"],
        ["Max deposition ΔZ",Number(d.deposition.max_delta_z_mm).toFixed(3)+" mm"],
        ["Positive samples",d.deposition.positive_sample_count]
      ]:[])
    ].map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");
    drawMonitorOverlay();
    $("monitorMessage").textContent=d.deposition
      ?"Surface scan complete. Overlay points are colored by deposition height relative to the saved baseline."
      :"Surface scan complete. Overlay points are colored by Z deviation.";
  }catch(err){
    $("monitorMessage").textContent="Surface scan failed: "+err.message;
  }
}



function drawSlicerPreview(plan){
  const canvas=$("slicerPreview");
  if(!canvas)return;
  const ctx=canvas.getContext("2d");
  const width=canvas.width;
  const height=canvas.height;
  ctx.clearRect(0,0,width,height);
  ctx.fillStyle="#0b1220";
  ctx.fillRect(0,0,width,height);

  if(!plan?.segments?.length){
    if($("slicerLayerPreview")){
      $("slicerLayerPreview").disabled=true;
      $("slicerLayerPreview").min="0";
      $("slicerLayerPreview").max="0";
      $("slicerLayerPreview").value="0";
      $("slicerLayerPreviewLabel").textContent="All layers";
    }
    ctx.fillStyle="#94a3b8";
    ctx.font="16px sans-serif";
    ctx.fillText("Slice an STL to preview syringe toolpaths.",24,36);
    return;
  }

  const allSegments=plan.segments.filter(s=>s.extruding);
  if(!allSegments.length){
    ctx.fillStyle="#94a3b8";
    ctx.font="16px sans-serif";
    ctx.fillText("No extruding syringe paths in this plan.",24,36);
    return;
  }

  const layers=[...new Set(allSegments.map(s=>Number(s.layer)||0))].sort((a,b)=>a-b);
  const slider=$("slicerLayerPreview");
  const showAll=$("slicerShowAllLayers")?.checked!==false;
  if(slider){
    slider.disabled=layers.length<=1||showAll;
    slider.min=String(layers[0]||0);
    slider.max=String(layers[layers.length-1]||0);
    if(Number(slider.value)>Number(slider.max))slider.value=slider.max;
    if(Number(slider.value)<Number(slider.min))slider.value=slider.min;
  }

  const selectedLayer=slider?Number(slider.value):(layers[0]||0);
  const segments=showAll
    ?allSegments
    :allSegments.filter(s=>(Number(s.layer)||0)===selectedLayer);

  if($("slicerLayerPreviewLabel")){
    $("slicerLayerPreviewLabel").textContent=showAll
      ?("All "+layers.length+" layers")
      :("Layer "+selectedLayer);
  }

  const xs=allSegments.flatMap(s=>[Number(s.start[0]),Number(s.end[0])]);
  const ys=allSegments.flatMap(s=>[Number(s.start[1]),Number(s.end[1])]);
  const min=[Math.min(...xs),Math.min(...ys),0];
  const max=[Math.max(...xs),Math.max(...ys),0];
  const dx=Math.max(1e-6,max[0]-min[0]);
  const dy=Math.max(1e-6,max[1]-min[1]);
  const pad=28;
  const scale=Math.min((width-pad*2)/dx,(height-pad*2)/dy);
  const ox=(width-dx*scale)/2-Number(min[0])*scale;
  const oy=(height-dy*scale)/2+Number(max[1])*scale;

  const minLayer=layers[0]||0;
  const maxLayer=layers[layers.length-1]||minLayer;
  const layerSpan=Math.max(1,maxLayer-minLayer);

  for(const s of segments){
    const t=((Number(s.layer)||0)-minLayer)/layerSpan;
    const hue=190+Math.round(95*t);
    ctx.strokeStyle="hsl("+hue+" 80% 60%)";
    ctx.globalAlpha=showAll?0.65:1;
    ctx.lineWidth=showAll?1.4:2.2;
    ctx.beginPath();
    ctx.moveTo(ox+Number(s.start[0])*scale,oy-Number(s.start[1])*scale);
    ctx.lineTo(ox+Number(s.end[0])*scale,oy-Number(s.end[1])*scale);
    ctx.stroke();
  }
  ctx.globalAlpha=1;

  ctx.strokeStyle="#475569";
  ctx.lineWidth=1;
  ctx.strokeRect(pad,pad,width-pad*2,height-pad*2);
  ctx.fillStyle="#cbd5e1";
  ctx.font="13px sans-serif";
  ctx.fillText(showAll
    ?("Top view · all extrusion paths · "+layers.length+" layer(s)")
    :("Top view · layer "+selectedLayer),pad,18);
}

function bytesToBase64(buffer){
  const bytes=new Uint8Array(buffer);
  let binary="";
  const chunk=0x8000;
  for(let i=0;i<bytes.length;i+=chunk){
    binary+=String.fromCharCode(...bytes.subarray(i,Math.min(i+chunk,bytes.length)));
  }
  return btoa(binary);
}

function renderSlicerPreflight(preflight, advisories=[]){
  const badge=$("slicerPreflightBadge");
  const title=$("slicerPreflightTitle");
  const list=$("slicerPreflight");
  const adv=$("slicerAdvisories");
  if(!preflight){
    badge.textContent="WAITING";
    badge.className="pill";
    title.textContent="Not evaluated";
    list.innerHTML="";
    adv.innerHTML="";
    return;
  }

  const ready=!!preflight.ready_for_physical_print;
  state.slicerPreflightReady=ready;
  badge.textContent=ready?"READY":"BLOCKED";
  badge.className="pill "+(ready?"ok":"bad");
  title.textContent=ready?"Ready for physical print":"Resolve blocking checks";

  list.innerHTML=(preflight.checks||[]).map(item=>
    "<div><span>"+esc(item.name)+"</span><strong>"+(item.ok?"PASS":"BLOCK")+"</strong><small>"+esc(item.message||"")+"</small></div>"
  ).join("");

  adv.innerHTML=(advisories||[]).map(item=>
    "<div><span>"+esc((item.level||"note").toUpperCase())+"</span><strong>"+esc(item.code||"process")+"</strong><small>"+esc(item.message||"")+"</small></div>"
  ).join("");
}

async function sliceStlForSyringe(){
  const file=$("slicerStlFile").files?.[0];
  if(!file){
    $("slicerMessage").textContent="Choose an STL file first.";
    return;
  }
  if(file.size>12*1024*1024){
    $("slicerMessage").textContent="STL exceeds the 12 MB Raspberry Pi slicer limit.";
    return;
  }

  const layerHeight=Number($("slicerLayerHeight").value);
  const beadWidth=Number($("slicerBeadWidth").value);
  const infill=Number($("slicerInfill").value);
  const syringeDiameter=Number($("slicerSyringeDiameter").value);
  const syringeCapacity=Number($("slicerSyringeCapacity").value);
  const needleDiameter=Number($("slicerNeedleDiameter").value);
  const alginatePercent=Number($("slicerAlginatePercent").value);
  const calciumMm=Number($("slicerCalciumMm").value);
  const extrusionMultiplier=Number($("slicerExtrusionMultiplier").value);
  const travelLift=Number($("slicerTravelLift").value);
  const crosslinkMode=$("slicerCrosslinkMode").value;
  const supportStrategy=$("slicerSupportStrategy").value;
  const temperatureMode=$("slicerTemperatureMode").value;
  const bedTemperature=Number($("slicerBedTemperature").value);
  const printFeed=Number($("slicerPrintFeed").value);
  const travelFeed=Number($("slicerTravelFeed").value);
  const eStepsCalibrated=$("slicerEstepsCalibrated").checked;
  const motorDirectionVerified=$("slicerMotorDirectionVerified").checked;

  const values=[layerHeight,beadWidth,infill,syringeDiameter,syringeCapacity,needleDiameter,alginatePercent,calciumMm,extrusionMultiplier,travelLift,bedTemperature,printFeed,travelFeed];
  if(values.some(v=>!Number.isFinite(v))){
    $("slicerMessage").textContent="Enter valid numeric slicer settings.";
    return;
  }

  $("sliceStl").disabled=true;
  $("downloadSlicedGcode").disabled=true;
  $("slicerMessage").textContent="Slicing "+file.name+" for syringe extrusion…";

  try{
    const buffer=await file.arrayBuffer();
    const d=await api("/api/slicer/stl",{
      method:"POST",
      body:JSON.stringify({
        filename:file.name,
        stl_base64:bytesToBase64(buffer),
        layer_height_mm:layerHeight,
        bead_width_mm:beadWidth,
        infill_percent:infill,
        syringe_diameter_mm:syringeDiameter,
        syringe_capacity_ml:syringeCapacity,
        needle_inner_diameter_mm:needleDiameter,
        alginate_percent_wv:alginatePercent,
        calcium_chloride_mM:calciumMm,
        crosslink_mode:crosslinkMode,
        support_strategy:supportStrategy,
        temperature_mode:temperatureMode,
        bed_temperature_c:bedTemperature,
        extrusion_multiplier:extrusionMultiplier,
        travel_lift_mm:travelLift,
        print_feed_mm_min:Math.round(printFeed),
        travel_feed_mm_min:Math.round(travelFeed),
        e_steps_calibrated:eStepsCalibrated,
        motor_direction_verified:motorDirectionVerified
      })
    });

    state.slicedGcode=d.gcode;
    state.slicedFilename=d.filename;
    const maxLayer=Math.max(0,Number(d.summary?.generated_layers||1)-1);
    if($("slicerLayerPreview")){
      $("slicerLayerPreview").min="0";
      $("slicerLayerPreview").max=String(maxLayer);
      $("slicerLayerPreview").value="0";
    }
    renderPlan(d.plan);
    drawSlicerPreview(d.plan);
    if(state.calibrationProfile)await loadProjectedPlan().catch(()=>{});

    const s=d.summary||{};
    $("slicerSummary").innerHTML=[
      ["Output",d.filename||"—"],
      ["Model size",(s.model_size_mm||[]).map(v=>Number(v).toFixed(2)).join(" × ")+" mm"],
      ["Triangles",s.triangle_count??"—"],
      ["Generated layers",s.generated_layers??"—"],
      ["Contour segments",s.contour_segments??"—"],
      ["Infill segments",s.infill_segments??"—"],
      ["Alginate",s.material_profile?.alginate_percent_wv==null?"—":Number(s.material_profile.alginate_percent_wv).toFixed(1)+"% w/v"],
      ["Crosslinking",s.crosslink_mode||"—"],
      ["Support strategy",s.support_strategy||"—"],
      ["Temperature",s.temperature_mode==="heated_bed"?(Number(s.bed_temperature_c).toFixed(0)+" °C bed"):"Ambient / heaters off"],
      ["Unsupported path",s.unsupported_path_ratio==null?"—":(Number(s.unsupported_path_ratio)*100).toFixed(1)+"%"],
      ["E per XY mm",s.e_per_xy_mm==null?"—":Number(s.e_per_xy_mm).toFixed(8)+" mm plunger/mm"],
      ["Estimated plunger travel",s.estimated_plunger_travel_mm==null?"—":Number(s.estimated_plunger_travel_mm).toFixed(4)+" mm"],
      ["Estimated deposited volume",s.estimated_volume_ml==null?"—":Number(s.estimated_volume_ml).toFixed(4)+" mL"]
    ].map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");

    renderSlicerPreflight(d.preflight||s.preflight,d.advisories||s.process_advisories||[]);
    $("downloadSlicedGcode").disabled=false;
    $("slicerMessage").textContent=(d.preflight?.ready_for_physical_print
      ?"Plan complete and preflight passed. The physical print runner is ready after you confirm the power cutoff."
      :"Plan complete. G-code is generated for preview, but physical printing is blocked by preflight items.");
    updatePrintStartReadiness();
  }catch(err){
    state.slicedGcode=null;
    state.slicedFilename=null;
    $("slicerSummary").innerHTML="";
    renderSlicerPreflight(null,[]);
    state.slicerPreflightReady=false;
    updatePrintStartReadiness();
    drawSlicerPreview(null);
    $("slicerMessage").textContent="Slice failed: "+err.message;
  }finally{
    $("sliceStl").disabled=false;
  }
}

function downloadSlicedGcode(){
  if(!state.slicedGcode||!state.slicedFilename)return;
  const blob=new Blob([state.slicedGcode],{type:"text/plain;charset=utf-8"});
  const url=URL.createObjectURL(blob);
  const a=document.createElement("a");
  a.href=url;
  a.download=state.slicedFilename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}

function updatePrintStartReadiness(){
  const running=!!state.printState?.running;
  const confirmed=!!$("confirmPhysicalStop")?.checked;
  const clearance=!!$("confirmXClearance")?.checked;
  const clean=!!$("confirmSurfaceClean")?.checked;
  $("startPhysicalPrint").disabled=running||!confirmed||!clearance||!clean;
}

function renderPrintRunner(p){
  state.printState=p||null;
  if(!p)return;
  const running=!!p.running;
  const paused=!!p.paused;
  const stateName=p.state||"IDLE";
  const ok=["IDLE","PRINTING","STARTING","PAUSED","COMPLETE"].includes(stateName);
  pill($("printRunnerBadge"),ok,stateName);
  $("printProgress").textContent=Number(p.progress_percent||0).toFixed(1)+"%";
  $("printLayer").textContent=p.current_layer==null?"—":String(Number(p.current_layer)+1);
  $("printCommands").textContent=Number(p.completed_commands||0)+" / "+Number(p.total_commands||0);

  $("pausePhysicalPrint").disabled=!running||paused;
  $("resumePhysicalPrint").disabled=!running||!paused;
  $("stopPhysicalPrint").disabled=!running;
  updatePrintStartReadiness();

  const monitor=p.monitoring||{};
  $("printVisionStatus").textContent=monitor.status||"NOT STARTED";
  const metrics=monitor.metrics||{};
  const rows=[];
  if(monitor.failure_type)rows.push(["Detected condition",monitor.failure_type]);
  if(metrics.coverage_percent!=null)rows.push(["Path coverage",Number(metrics.coverage_percent).toFixed(1)+"%"]);
  if(metrics.within_tolerance_percent!=null)rows.push(["Within tolerance",Number(metrics.within_tolerance_percent).toFixed(1)+"%"]);
  if(metrics.missing_path_samples!=null)rows.push(["Missing samples",metrics.missing_path_samples]);
  if(metrics.excess_off_path_samples!=null)rows.push(["Off-path samples",metrics.excess_off_path_samples]);
  $("printVisionDetails").innerHTML=rows.map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");

  if(running&&!state.printCameraActive)startPrintCameraView().catch(()=>{});
  if(!running&&["COMPLETE","STOPPED","ERROR","EMERGENCY_STOP"].includes(stateName)&&state.printCameraActive){
    stopPrintCameraView();
  }

  if(p.error){
    $("printRunnerMessage").textContent="Print error: "+p.error;
  }else if(monitor.message&&monitor.last_checked_layer!=null){
    $("printRunnerMessage").textContent="Layer "+(Number(monitor.last_checked_layer)+1)+": "+monitor.message;
  }else if(stateName==="COMPLETE"){
    $("printRunnerMessage").textContent="Print completed. Run final quality analysis for the full surface.";
  }else if(stateName==="STOPPED"){
    $("printRunnerMessage").textContent="Stopped sending new G-code. Buffered printer motion may finish; use Emergency Stop or physical power for an immediate stop.";
  }else if(running){
    $("printRunnerMessage").textContent="Printing "+(p.filename||"plan")+" · "+Number(p.progress_percent||0).toFixed(1)+"% complete.";
  }
}

async function loadPrintRunner(){
  const p=await api("/api/print/status");
  renderPrintRunner(p);
  return p;
}

async function startPrintCameraView(){
  if(state.printCameraActive)return;
  try{
    const live=await api("/api/camera/live/status");
    if(!live.running){
      const started=await api("/api/camera/live/start",{method:"POST"});
      if(started.error)throw new Error(started.error);
    }
  }catch(err){
    $("printCameraPlaceholder").textContent="D405 unavailable: "+err.message;
    return;
  }

  state.printCameraActive=true;
  const generation=++state.printCameraGeneration;
  $("printCameraPlaceholder").textContent="Starting D405 live view…";

  while(state.printCameraActive&&generation===state.printCameraGeneration){
    try{
      const blob=await fetchCameraBlob("/api/camera/color.jpg");
      const next=URL.createObjectURL(blob);
      const prev=state.printCameraObjectUrl;
      state.printCameraObjectUrl=next;
      $("printCameraImage").src=next;
      $("printCameraImage").classList.add("visible");
      $("printCameraPlaceholder").style.display="none";
      $("printCameraStage").classList.add("has-image");
      if(prev)URL.revokeObjectURL(prev);
    }catch(err){
      $("printCameraPlaceholder").style.display="";
      $("printCameraPlaceholder").textContent="D405 live view error: "+err.message;
    }
    await new Promise(resolve=>setTimeout(resolve,500));
  }
}

function stopPrintCameraView(){
  state.printCameraActive=false;
  state.printCameraGeneration++;
  if(state.printCameraObjectUrl){
    URL.revokeObjectURL(state.printCameraObjectUrl);
    state.printCameraObjectUrl=null;
  }
  $("printCameraImage").classList.remove("visible");
  $("printCameraImage").removeAttribute("src");
  $("printCameraPlaceholder").style.display="";
  $("printCameraPlaceholder").textContent="D405 live view will start with the print.";
}

async function startPhysicalPrint(){
  if(!$("confirmPhysicalStop").checked){
    $("printRunnerMessage").textContent="Confirm that the physical power cutoff is immediately reachable.";
    return;
  }
  if(!$("confirmXClearance").checked){
    $("printRunnerMessage").textContent="Verify Enderstruder/X-endstop clearance before homing.";
    return;
  }
  if(!$("confirmSurfaceClean").checked){
    $("printRunnerMessage").textContent="Confirm the print surface is clean so the D405 can capture a fresh baseline.";
    return;
  }

  if(!confirm("Run the automatic pre-print calibration sequence, then start the print only if every physical preflight check passes?"))return;
  $("printRunnerMessage").textContent="Running pre-print calibration: printer/endstops → D405 → saved transform → nozzle reference → clean-surface baseline…";
  $("preprintCalibrationDetails").innerHTML="";
  try{
    await startPrintCameraView();
    const p=await api("/api/print/start",{
      method:"POST",
      body:JSON.stringify({
        confirm_physical_stop_available:true,
        confirm_x_endstop_clearance:true,
        confirm_surface_clean:true,
        run_preprint_calibration:true
      })
    });
    if(p.preprint_calibration?.steps){
      $("preprintCalibrationDetails").innerHTML=p.preprint_calibration.steps.map(step=>
        "<div><span>"+esc(step.name)+"</span><strong>"+(step.ok?"PASS":"BLOCK")+"</strong><small>"+esc(step.detail||"")+"</small></div>"
      ).join("");
    }
    renderPrintRunner(p);
  }catch(err){
    $("printRunnerMessage").textContent="Calibration/start blocked: "+err.message;
    $("preprintCalibrationDetails").innerHTML=
      '<div><span>Pre-print sequence</span><strong>BLOCKED</strong><small>'+esc(err.message)+'</small></div>';
    await loadCalibration().catch(()=>{});
    await loadPrintRunner().catch(()=>{});
  }
}

async function pausePhysicalPrint(){
  try{renderPrintRunner(await api("/api/print/pause",{method:"POST"}))}
  catch(err){$("printRunnerMessage").textContent=err.message}
}
async function resumePhysicalPrint(){
  try{renderPrintRunner(await api("/api/print/resume",{method:"POST"}))}
  catch(err){$("printRunnerMessage").textContent=err.message}
}
async function stopPhysicalPrint(){
  if(!confirm("Stop sending new G-code after the current command? This is not an emergency stop."))return;
  try{renderPrintRunner(await api("/api/print/stop",{method:"POST"}))}
  catch(err){$("printRunnerMessage").textContent=err.message}
}

function renderPlan(plan){
  state.planSummary=plan||null;
  const loaded=!!plan;
  pill($("planBadge"),loaded,loaded?"PLAN LOADED":"NO PLAN");

  if(!loaded){
    drawSlicerPreview(null);
    $("planDetails").innerHTML='<div><span>Status</span><strong>No G-code loaded</strong></div>';
    $("planMessage").textContent="No print plan loaded.";
    state.projectedPlan=null;
    drawMonitorOverlay();
    updateAnalyticsReadiness();
    return;
  }

  const min=plan.bounds_mm?.min||[0,0,0];
  const max=plan.bounds_mm?.max||[0,0,0];
  $("planDetails").innerHTML=[
    ["File",plan.filename||"—"],
    ["Segments",plan.segment_count],
    ["Extruding segments",plan.extruding_segment_count],
    ["Estimated layers",plan.layer_count_estimate],
    ["Motion",Number(plan.total_motion_mm||0).toFixed(1)+" mm"],
    ["Extruding path",Number(plan.extruding_motion_mm||0).toFixed(1)+" mm"],
    ["Estimated motion time",formatDuration(plan.estimated_time_seconds)],
    ["X range",Number(min[0]).toFixed(1)+" → "+Number(max[0]).toFixed(1)+" mm"],
    ["Y range",Number(min[1]).toFixed(1)+" → "+Number(max[1]).toFixed(1)+" mm"],
    ["Z range",Number(min[2]).toFixed(1)+" → "+Number(max[2]).toFixed(1)+" mm"]
  ].map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");

  $("planMessage").textContent="Plan parsed. It will appear as the expected extrusion path in Monitor after camera calibration.";
  if(plan.slicer?.preflight){
    renderSlicerPreflight(plan.slicer.preflight,plan.slicer.process_advisories||[]);
  }else{
    state.slicerPreflightReady=false;
    updatePrintStartReadiness();
  }
  drawSlicerPreview(plan);
  updateAnalyticsReadiness();
}

async function loadPlan(){
  const d=await api("/api/plan");
  renderPlan(d.plan);
  if(d.loaded&&state.calibrationProfile){
    await loadProjectedPlan().catch(()=>{});
  }
  return d.plan;
}

async function loadProjectedPlan(){
  if(!state.planSummary||!state.calibrationProfile){
    state.projectedPlan=null;
    drawMonitorOverlay();
    return null;
  }
  const d=await api("/api/plan/projected");
  state.projectedPlan=d;
  drawMonitorOverlay();
  if($("monitorMessage")&&state.monitorActive){
    $("monitorMessage").textContent="Observe mode active. Cyan overlay = expected extruding G-code path. Click the image to query printer X/Y/Z.";
  }
  return d;
}

async function loadGcodeFile(){
  const file=$("gcodeFile").files?.[0];
  if(!file){
    $("planMessage").textContent="Choose a G-code file first.";
    return;
  }

  $("planMessage").textContent="Reading and parsing "+file.name+"…";
  $("loadGcode").disabled=true;
  try{
    const text=await file.text();
    const d=await api("/api/plan",{
      method:"POST",
      body:JSON.stringify({filename:file.name,text})
    });
    renderPlan(d.plan);
    if(state.calibrationProfile)await loadProjectedPlan();
    $("planMessage").textContent="G-code parsed successfully. Expected extrusion geometry is ready for Monitor.";
  }catch(err){
    $("planMessage").textContent="G-code load failed: "+err.message;
  }finally{
    $("loadGcode").disabled=false;
  }
}

async function clearGcode(){
  if(!confirm("Clear the active G-code print plan?"))return;
  await api("/api/plan",{method:"DELETE"});
  state.projectedPlan=null;
  renderPlan(null);
}


function formatDuration(seconds){
  if(seconds==null)return "—";
  const s=Math.max(0,Math.round(Number(seconds)||0));
  const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=s%60;
  return [h?h+"h":"",m?m+"m":"",sec+"s"].filter(Boolean).join(" ");
}

function renderExperimentState(active,recent=[]){
  state.activeExperiment=active||null;
  const running=!!active;
  pill($("experimentBadge"),running,running?"RECORDING":"IDLE");
  $("startExperiment").disabled=running;
  $("captureExperimentSnapshot").disabled=!running;
  $("stopExperiment").disabled=!running;
  $("experimentName").disabled=running;

  if(running){
    const planName=active.plan?.filename||"No G-code plan";
    const calibrated=active.calibration?.camera_to_printer?"Yes":"No";
    $("experimentDetails").innerHTML=[
      ["Name",active.name],
      ["Mode",active.mode||"OBSERVE"],
      ["Calibration",calibrated],
      ["G-code",planName],
      ["Events",active.event_count||0],
      ["Snapshots",active.snapshot_count||0]
    ].map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");
    $("experimentMessage").textContent="Recording research events in OBSERVE mode. Monitor probes and surface scans are logged automatically.";
  }else{
    $("experimentDetails").innerHTML='<div><span>Status</span><strong>No active session</strong></div>';
    $("experimentMessage").textContent="Experiments run in OBSERVE mode and do not command the printer.";
  }

  $("recentExperiments").innerHTML=recent.length?recent.map(item=>{
    const complete=!!item.ended_at_unix;
    const started=item.started_at_unix?new Date(item.started_at_unix*1000).toLocaleString():"—";
    const duration=complete?formatDuration(item.duration_seconds):"Running";
    return '<div class="experiment-item">'+
      '<div><strong>'+esc(item.name||"Experiment")+'</strong><small>'+esc(started)+'</small></div>'+
      '<div><small>Mode</small><strong>'+esc(item.mode||"OBSERVE")+'</strong></div>'+
      '<div><small>Snapshots</small><strong>'+esc(item.snapshot_count||0)+'</strong></div>'+
      '<div><span class="experiment-state '+(complete?"complete":"active")+'">'+(complete?"COMPLETE":"ACTIVE")+'</span><small>'+esc(duration)+'</small></div>'+
      '</div>';
  }).join(""):'<p class="muted">No saved experiments yet.</p>';
}

async function loadExperiments(){
  const d=await api("/api/experiment");
  renderExperimentState(d.active,d.recent||[]);
  return d;
}

async function startExperimentSession(){
  const name=$("experimentName").value.trim()||"Bioprinter experiment";
  $("experimentMessage").textContent="Starting experiment…";
  try{
    const d=await api("/api/experiment/start",{
      method:"POST",
      body:JSON.stringify({name})
    });
    await loadExperiments();
    $("experimentMessage").textContent="Experiment started. Calibration and active G-code metadata were captured.";
  }catch(err){
    $("experimentMessage").textContent="Unable to start experiment: "+err.message;
  }
}

async function captureExperimentSnapshot(){
  $("experimentMessage").textContent="Capturing synchronized RGB + depth snapshot…";
  try{
    const d=await api("/api/experiment/snapshot",{method:"POST"});
    await loadExperiments();
    $("experimentMessage").textContent="Snapshot "+d.snapshot.index+" recorded with RGB, depth, and center depth measurement.";
  }catch(err){
    $("experimentMessage").textContent="Snapshot failed: "+err.message;
  }
}

async function stopExperimentSession(){
  if(!confirm("Stop the active experiment and finalize its metadata?"))return;
  $("experimentMessage").textContent="Finalizing experiment…";
  try{
    const d=await api("/api/experiment/stop",{method:"POST"});
    await loadExperiments();
    $("experimentMessage").textContent="Experiment complete. Duration: "+formatDuration(d.experiment.duration_seconds)+".";
  }catch(err){
    $("experimentMessage").textContent="Unable to stop experiment: "+err.message;
  }
}


function calculateSyringeMotion(){
  const diameter=Number($("syringeDiameter").value);
  const gear=Number($("syringeGearRatio").value);
  const pitch=Number($("syringeLeadPitch").value);
  const motorSteps=Number($("syringeMotorSteps").value);
  const microsteps=Number($("syringeMicrosteps").value);
  const volumeMl=Number($("syringeVolume").value);
  const pathLength=Number($("syringePathLength").value);

  const values=[diameter,gear,pitch,motorSteps,microsteps,volumeMl];
  if(values.some(v=>!Number.isFinite(v))||diameter<=0||gear<=0||pitch<=0||motorSteps<=0||microsteps<=0||volumeMl<0){
    $("syringeMotionResults").innerHTML='<div><span>Status</span><strong>Enter valid positive mechanics values and a non-negative volume.</strong></div>';
    return;
  }

  const radius=diameter/2;
  const area=Math.PI*radius*radius;
  const volumeMm3=volumeMl*1000;
  const plungerMm=volumeMm3/area;
  const motorRevs=plungerMm*gear/pitch;
  const theoreticalEstepsPerMm=motorSteps*microsteps*gear/pitch;
  const totalMicrosteps=plungerMm*theoreticalEstepsPerMm;
  const mlPerPlungerMm=area/1000;
  const ePerPathMm=pathLength>0?plungerMm/pathLength:null;
  const ulPerPathMm=pathLength>0?(volumeMl*1000)/pathLength:null;

  const rows=[
    ["Syringe cross-section",area.toFixed(2)+" mm²"],
    ["Volume per 1 mm plunger",mlPerPlungerMm.toFixed(4)+" mL"],
    ["Theoretical E-steps/mm",theoreticalEstepsPerMm.toFixed(1)+" microsteps/mm"],
    ["Requested plunger travel / E Δ",plungerMm.toFixed(4)+" mm"],
    ["Motor rotation",motorRevs.toFixed(4)+" rev"],
    ["Total motor microsteps",Math.round(totalMicrosteps).toLocaleString()],
  ];
  if(ePerPathMm!==null){
    rows.push(["E per path mm",ePerPathMm.toFixed(6)+" mm E/mm XY"]);
    rows.push(["Volume per path mm",ulPerPathMm.toFixed(3)+" µL/mm"]);
  }
  $("syringeMotionResults").innerHTML=rows.map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");
}

function updateAnalyticsReadiness(){
  const calibrated=!!state.calibrationProfile;
  const baseline=!!state.calibrationProfile?.surface_baseline;
  const plan=!!state.planSummary;
  const ready=calibrated&&baseline&&plan;
  pill($("qualityReadinessBadge"),ready,ready?"READY":"SETUP REQUIRED");
  $("runQualityAnalysis").disabled=!ready;

  if(!calibrated){
    $("qualityMessage").textContent="Camera-to-printer calibration is required.";
  }else if(!baseline){
    $("qualityMessage").textContent="Save a clean reference surface in Calibration.";
  }else if(!plan){
    $("qualityMessage").textContent="Load the experiment G-code on the Print page.";
  }else if(!state.qualityResult){
    $("qualityMessage").textContent="Ready for observe-only expected-vs-observed surface analysis.";
  }
}

function qualityColor(classification){
  return {
    within_tolerance:"#22c55e",
    too_low:"#eab308",
    too_high:"#f97316",
    missing:"#ef4444",
    excess:"#d946ef",
    background:"#64748b"
  }[classification]||"#64748b";
}

function drawQualityOverlay(){
  const canvas=$("qualityCanvas");
  const img=$("qualityImage");
  setupCanvasForImage(img,canvas);
  if(!canvas.width||!canvas.height)return;
  const ctx=canvas.getContext("2d");
  ctx.clearRect(0,0,canvas.width,canvas.height);

  const points=state.qualityResult?.points||[];
  for(const point of points){
    ctx.beginPath();
    ctx.arc(point.u,point.v,5,0,Math.PI*2);
    ctx.fillStyle=qualityColor(point.classification);
    ctx.globalAlpha=point.classification==="background"?.25:.9;
    ctx.fill();
  }
  ctx.globalAlpha=1;

  if(state.projectedPlan?.segments?.length){
    ctx.save();
    ctx.strokeStyle="#38bdf8";
    ctx.lineWidth=1.5;
    ctx.globalAlpha=.4;
    ctx.beginPath();
    for(const segment of state.projectedPlan.segments){
      ctx.moveTo(segment.start[0],segment.start[1]);
      ctx.lineTo(segment.end[0],segment.end[1]);
    }
    ctx.stroke();
    ctx.restore();
  }
}

function renderQualityResult(result){
  state.qualityResult=result;
  $("qualityCoverage").textContent=result.coverage_percent==null?"—":Number(result.coverage_percent).toFixed(1)+"%";
  $("qualityToleranceRate").textContent=result.within_tolerance_percent==null?"—":Number(result.within_tolerance_percent).toFixed(1)+"%";
  $("qualityMissing").textContent=result.missing_path_samples??"—";
  $("qualityExcess").textContent=result.excess_off_path_samples??"—";
  $("qualityMeanAbs").textContent=result.mean_abs_height_error_mm==null?"—":Number(result.mean_abs_height_error_mm).toFixed(3)+" mm";
  $("qualityRms").textContent=result.rms_height_error_mm==null?"—":Number(result.rms_height_error_mm).toFixed(3)+" mm";
  const advisory=result.advisory_status||"NO DATA";
  const ok=advisory==="NORMAL";
  $("qualityAdvisoryBadge").textContent=advisory;
  $("qualityAdvisoryBadge").className="pill "+(ok?"ok":advisory==="WARNING"?"":"bad");
  $("qualityAdvisoryReasons").textContent=(result.advisory_reasons||[]).join(" ");
  drawQualityOverlay();
}

async function runQualityAnalysis(){
  updateAnalyticsReadiness();
  if($("runQualityAnalysis").disabled)return;

  $("qualityMessage").textContent="Capturing D405 surface and comparing it with expected G-code geometry…";
  $("runQualityAnalysis").disabled=true;
  try{
    await ensureCalibrationCamera();

    const imageBlob=await fetchCameraBlob("/api/camera/color.jpg");
    if(state.qualityObjectUrl)URL.revokeObjectURL(state.qualityObjectUrl);
    state.qualityObjectUrl=URL.createObjectURL(imageBlob);
    const img=$("qualityImage");
    img.onload=()=>{
      setupCanvasForImage(img,$("qualityCanvas"));
      $("qualityStage").classList.add("has-image");
      drawQualityOverlay();
    };
    img.src=state.qualityObjectUrl;

    if(!state.projectedPlan)await loadProjectedPlan();

    const payload={
      columns:14,
      rows:10,
      path_radius_mm:Number($("qualityPathRadius").value),
      min_deposition_height_mm:Number($("qualityMinHeight").value),
      height_tolerance_mm:Number($("qualityHeightTolerance").value)
    };
    const result=await api("/api/quality/final-surface",{
      method:"POST",
      body:JSON.stringify(payload)
    });
    renderQualityResult(result);
    $("qualityMessage").textContent="Quality scan complete. Results are observe-only research measurements.";
  }catch(err){
    $("qualityMessage").textContent="Quality analysis failed: "+err.message;
  }finally{
    updateAnalyticsReadiness();
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
    '<div class="saved-item">'+
      '<div class="wifi-meta"><strong>'+esc(n.name)+(n.active?" ✓":"")+'</strong>'+
      '<small>Autoconnect '+(n.autoconnect?"on":"off")+' · Priority '+Number(n.priority||0)+'</small></div>'+
      '<div class="locked-controls">'+
        '<input class="wifi-priority" data-n="'+esc(n.name)+'" type="number" min="-999" max="999" step="10" value="'+Number(n.priority||0)+'" aria-label="Priority for '+esc(n.name)+'">'+
        '<button class="secondary wifi-save-priority" data-n="'+esc(n.name)+'">Save priority</button>'+
        '<button class="secondary wifi-activate" data-n="'+esc(n.name)+'" '+(n.active?"disabled":"")+'>Use now</button>'+
        '<button class="danger-outline wifi-forget" data-n="'+esc(n.name)+'">Forget</button>'+
      '</div>'+
    '</div>'
  ).join("")||'<p class="muted">No saved Wi-Fi profiles.</p>';

  $("savedNetworks").querySelectorAll(".wifi-save-priority").forEach(b=>b.onclick=async()=>{
    const input=$("savedNetworks").querySelector('.wifi-priority[data-n="'+CSS.escape(b.dataset.n)+'"]');
    const priority=Number(input?.value);
    if(!Number.isInteger(priority)||priority<-999||priority>999)return;
    b.disabled=true;
    try{
      await api("/api/network/priority",{method:"POST",body:JSON.stringify({connection:b.dataset.n,priority})});
      await saved();
    }catch(err){
      alert("Unable to set Wi-Fi priority: "+err.message);
      b.disabled=false;
    }
  });

  $("savedNetworks").querySelectorAll(".wifi-activate").forEach(b=>b.onclick=async()=>{
    if(!confirm("Switch the Raspberry Pi to "+b.dataset.n+" now? This page may briefly disconnect."))return;
    try{
      await api("/api/network/activate",{method:"POST",body:JSON.stringify({connection:b.dataset.n})});
    }catch(err){
      if(!String(err.message).includes("Failed to fetch"))alert(err.message);
    }
  });

  $("savedNetworks").querySelectorAll(".wifi-forget").forEach(b=>b.onclick=async()=>{
    if(confirm("Forget "+b.dataset.n+"?")){
      await api("/api/network/forget",{method:"POST",body:JSON.stringify({connection:b.dataset.n})});
      saved();
    }
  });
}

async function remoteAccess(){
  const d=await api("/api/network/remote");
  pill($("remoteAccessBadge"),d.active,d.active?"ONLINE":(d.configured?"OFFLINE":"NOT CONFIGURED"));
  $("remoteAccessUrl").textContent=d.public_url||"Not configured";
  $("remoteAccessService").textContent=d.service||"cloudflared.service";
  $("remoteAccessMessage").textContent=d.active
    ?"Remote HTTPS access is active. The Pi keeps this tunnel alive whenever it has Internet connectivity."
    :d.configured
      ?"Remote access is configured but the tunnel service is not currently active."
      :"Run the one-time Cloudflare Tunnel setup on the Pi, then this page will show the public controller URL.";
}

function activatePage(page){
  const current=document.querySelector(".nav-btn.active")?.dataset.page;
  if(current==="camera"&&page!=="camera"&&state.liveCamera){
    stopLiveCamera().catch(()=>{});
  }
  if(current==="monitor"&&page!=="monitor"&&state.monitorActive){
    stopMonitor().catch(()=>{});
  }
  if(current==="calibration"&&!["calibration","camera","monitor"].includes(page)){
    api("/api/camera/live/stop",{method:"POST"}).catch(()=>{});
  }

  document.querySelectorAll(".nav-btn,.page").forEach(x=>x.classList.remove("active"));
  const nav=document.querySelector('.nav-btn[data-page="'+page+'"]');
  if(nav)nav.classList.add("active");
  $("page-"+page).classList.add("active");
  $("pageTitle").textContent=page[0].toUpperCase()+page.slice(1);

  if(page==="network"){saved().catch(()=>{});hotspot().catch(()=>{});remoteAccess().catch(()=>{})}
  if(page==="printer"){printer().catch(()=>{});loadCommissioning().catch(()=>{})}
  if(page==="camera"){camera().catch(()=>{})}
  if(page==="calibration"){loadCalibration().catch(()=>{})}
  if(page==="monitor"){
    Promise.allSettled([loadCalibration(),loadPlan()]).then(()=>loadProjectedPlan().catch(()=>{}));
  }
  if(page==="print"){loadPlan().catch(()=>{});loadPrintRunner().catch(()=>{})}
  if(page==="experiments"){loadExperiments().catch(()=>{})}
  if(page==="analytics"){
    Promise.allSettled([loadCalibration(),loadPlan()]).then(()=>{
      loadProjectedPlan().catch(()=>{});
      updateAnalyticsReadiness();
    });
  }
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
$("homeCenter").onclick=()=>homeCenter();

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

$("captureCalibrationFrame").onclick=()=>captureCalibrationFrame();
$("resetCalibrationPoints").onclick=()=>resetCalibrationPoints();
$("solveCalibration").onclick=()=>solveCalibration();
$("clearCalibration").onclick=()=>clearCalibration().catch(e=>$("calibrationMessage").textContent=e.message);
$("markNozzleTip").onclick=()=>beginNozzleMark();
$("analyzeCalibrationSurface").onclick=()=>analyzeCalibrationSurface();
$("saveSurfaceBaseline").onclick=()=>saveCalibrationSurfaceBaseline();
$("calibrationCanvas").onclick=e=>calibrationCanvasClick(e);

$("startMonitor").onclick=()=>startMonitor();
$("stopMonitor").onclick=()=>stopMonitor();
$("monitorSurfaceScan").onclick=()=>analyzeMonitorSurface();
$("monitorCanvas").onclick=e=>monitorCanvasClick(e);

$("loadGcode").onclick=()=>loadGcodeFile();
$("clearGcode").onclick=()=>clearGcode().catch(e=>$("planMessage").textContent=e.message);
$("sliceStl").onclick=()=>sliceStlForSyringe();
$("downloadSlicedGcode").onclick=()=>downloadSlicedGcode();
$("confirmPhysicalStop").onchange=()=>updatePrintStartReadiness();
$("confirmXClearance").onchange=()=>updatePrintStartReadiness();
$("confirmSurfaceClean").onchange=()=>updatePrintStartReadiness();
$("startPhysicalPrint").onclick=()=>startPhysicalPrint();
$("pausePhysicalPrint").onclick=()=>pausePhysicalPrint();
$("resumePhysicalPrint").onclick=()=>resumePhysicalPrint();
$("stopPhysicalPrint").onclick=()=>stopPhysicalPrint();
$("slicerLayerPreview").oninput=()=>drawSlicerPreview(state.planSummary);
$("slicerShowAllLayers").onchange=()=>drawSlicerPreview(state.planSummary);
$("slicerTemperatureMode").onchange=()=>{
  const heated=$("slicerTemperatureMode").value==="heated_bed";
  $("slicerBedTemperature").disabled=!heated;
  if(!heated)$("slicerBedTemperature").value="0";
};
$("calculateSyringeMotion").onclick=()=>calculateSyringeMotion();

$("startExperiment").onclick=()=>startExperimentSession();
$("captureExperimentSnapshot").onclick=()=>captureExperimentSnapshot();
$("stopExperiment").onclick=()=>stopExperimentSession();
$("refreshExperiments").onclick=()=>loadExperiments().catch(e=>$("experimentMessage").textContent=e.message);

$("runQualityAnalysis").onclick=()=>runQualityAnalysis();

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
  remoteAccess().catch(()=>{});
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
      await Promise.allSettled([status(),printer(),camera(),loadCommissioning(),loadCalibration(),loadPlan(),loadExperiments()]);
    }catch{}
  }
  calculateSyringeMotion();
  drawSlicerPreview(state.planSummary);
  setInterval(()=>{if(state.token)status().catch(()=>{})},10000);
  setInterval(()=>{if(state.token)loadPrintRunner().catch(()=>{})},1500);
})();


window.startLiveCamera=startLiveCamera;
window.stopLiveCamera=stopLiveCamera;
