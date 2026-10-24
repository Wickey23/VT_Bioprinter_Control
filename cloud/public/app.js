const $=id=>document.getElementById(id);

function pill(el, ok, text){
  el.textContent=text;
  el.className="pill "+(ok?"ok":"bad");
}

async function refresh(){
  try{
    const [healthRes,deviceRes]=await Promise.all([
      fetch("/api/health",{cache:"no-store"}),
      fetch("/api/device/status",{cache:"no-store"})
    ]);
    const health=await healthRes.json();
    const device=await deviceRes.json();

    $("cloudState").textContent=health.ok?"ONLINE":"ERROR";
    $("dot").classList.toggle("online",!!health.ok);
    $("footerText").textContent=health.ok?"Cloud online":"Cloud error";

    $("piState").textContent=device.online?"ONLINE":(device.paired?"OFFLINE":"NOT PAIRED");
    $("piName").textContent=device.hostname||"Not paired";
    $("printerState").textContent=device.printer_connected?"CONNECTED":"OFFLINE";
    $("cameraState").textContent=device.camera_connected?"CONNECTED":"OFFLINE";

    if(device.online){
      $("heroTitle").textContent="Bioprinter connected";
      $("heroText").textContent="The Raspberry Pi device session is online.";
      pill($("heroBadge"),true,"DEVICE ONLINE");
      $("pairTitle").textContent="Raspberry Pi paired";
    }else{
      $("heroTitle").textContent="Cloud dashboard online";
      $("heroText").textContent="Vercel is deployed. Raspberry Pi pairing is the next step.";
      pill($("heroBadge"),false,"PI NOT PAIRED");
      $("pairTitle").textContent="Pi relay not paired";
    }
    $("pairMessage").textContent=device.message||"";
  }catch(err){
    $("cloudState").textContent="ERROR";
    $("heroTitle").textContent="Cloud API unavailable";
    $("heroText").textContent=err.message;
    pill($("heroBadge"),false,"ERROR");
    $("footerText").textContent="Cloud error";
  }
}

$("refresh").onclick=refresh;
refresh();
setInterval(refresh,10000);
