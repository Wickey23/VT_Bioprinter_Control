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
  projectedPlan:null
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
      ctx.fillStyle=zColor(point.z_mm);
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
      ctx.fillStyle=zColor(point.z_mm);
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
  $("monitorSurfaceScan").disabled=!valid;

  if(!valid){
    $("calibrationDetails").innerHTML='<div><span>Status</span><strong>No saved profile</strong></div>';
    pill($("nozzleBadge"),false,"NOT SET");
    $("nozzleDetails").innerHTML="";
    $("calibrationMessage").textContent="Capture a camera frame, then click the four bed corners in printer-coordinate order.";
    renderMonitorCalibration();
    return;
  }

  const rms=profile.camera_to_printer?.rms_corner_error_mm;
  $("calibrationDetails").innerHTML=[
    ["Camera",profile.camera?.model||"D405"],
    ["Serial",profile.camera?.serial||"—"],
    ["Bed",Number(profile.bed?.width_mm).toFixed(1)+" × "+Number(profile.bed?.depth_mm).toFixed(1)+" mm"],
    ["Corner-fit RMS",rms==null?"—":Number(rms).toFixed(3)+" mm"],
    ["Transform",profile.camera_to_printer?.method||"—"]
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
  el.innerHTML=[
    ["Samples",data.sample_count],
    ["Mean Z",Number(data.mean_z_mm).toFixed(3)+" mm"],
    ["RMS Z",Number(data.rms_z_mm).toFixed(3)+" mm"],
    ["Peak-to-peak",Number(data.peak_to_peak_mm).toFixed(3)+" mm"]
  ].map(x=>'<div><span>'+x[0]+'</span><strong>'+x[1]+'</strong></div>').join("");
}

async function analyzeCalibrationSurface(){
  $("calibrationMessage").textContent="Sampling calibrated bed surface…";
  try{
    const d=await api("/api/calibration/surface",{
      method:"POST",
      body:JSON.stringify({columns:12,rows:9})
    });
    state.calibrationSurface=d;
    renderSurfaceMetrics("surfaceMetrics",d);
    pill($("surfaceBadge"),true,"SCANNED");
    drawCalibrationOverlay();
    $("calibrationMessage").textContent="Surface map captured. Green points are near Z=0; yellow/red indicate larger deviation.";
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
    ["Nozzle",profile.nozzle_reference?"Referenced":"Not marked"]
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
}

async function monitorLoop(generation){
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
      ["Peak-to-peak",Number(d.peak_to_peak_mm).toFixed(3)+" mm"]
    ].map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");
    drawMonitorOverlay();
    $("monitorMessage").textContent="Surface scan complete. Overlay points are colored by Z deviation.";
  }catch(err){
    $("monitorMessage").textContent="Surface scan failed: "+err.message;
  }
}


function renderPlan(plan){
  state.planSummary=plan||null;
  const loaded=!!plan;
  pill($("planBadge"),loaded,loaded?"PLAN LOADED":"NO PLAN");

  if(!loaded){
    $("planDetails").innerHTML='<div><span>Status</span><strong>No G-code loaded</strong></div>';
    $("planMessage").textContent="No print plan loaded.";
    state.projectedPlan=null;
    drawMonitorOverlay();
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
    ["X range",Number(min[0]).toFixed(1)+" → "+Number(max[0]).toFixed(1)+" mm"],
    ["Y range",Number(min[1]).toFixed(1)+" → "+Number(max[1]).toFixed(1)+" mm"],
    ["Z range",Number(min[2]).toFixed(1)+" → "+Number(max[2]).toFixed(1)+" mm"]
  ].map(x=>"<div><span>"+esc(x[0])+"</span><strong>"+esc(x[1])+"</strong></div>").join("");

  $("planMessage").textContent="Plan parsed. It will appear as the expected extrusion path in Monitor after camera calibration.";
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

  if(page==="network"){saved().catch(()=>{});hotspot().catch(()=>{})}
  if(page==="printer"){printer().catch(()=>{});loadCommissioning().catch(()=>{})}
  if(page==="camera"){camera().catch(()=>{})}
  if(page==="calibration"){loadCalibration().catch(()=>{})}
  if(page==="monitor"){
    Promise.allSettled([loadCalibration(),loadPlan()]).then(()=>loadProjectedPlan().catch(()=>{}));
  }
  if(page==="print"){loadPlan().catch(()=>{})}
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

$("captureCalibrationFrame").onclick=()=>captureCalibrationFrame();
$("resetCalibrationPoints").onclick=()=>resetCalibrationPoints();
$("solveCalibration").onclick=()=>solveCalibration();
$("clearCalibration").onclick=()=>clearCalibration().catch(e=>$("calibrationMessage").textContent=e.message);
$("markNozzleTip").onclick=()=>beginNozzleMark();
$("analyzeCalibrationSurface").onclick=()=>analyzeCalibrationSurface();
$("calibrationCanvas").onclick=e=>calibrationCanvasClick(e);

$("startMonitor").onclick=()=>startMonitor();
$("stopMonitor").onclick=()=>stopMonitor();
$("monitorSurfaceScan").onclick=()=>analyzeMonitorSurface();
$("monitorCanvas").onclick=e=>monitorCanvasClick(e);

$("loadGcode").onclick=()=>loadGcodeFile();
$("clearGcode").onclick=()=>clearGcode().catch(e=>$("planMessage").textContent=e.message);

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
      await Promise.allSettled([status(),printer(),camera(),loadCommissioning(),loadCalibration(),loadPlan()]);
    }catch{}
  }
  setInterval(()=>{if(state.token)status().catch(()=>{})},10000);
})();


window.startLiveCamera=startLiveCamera;
window.stopLiveCamera=stopLiveCamera;
