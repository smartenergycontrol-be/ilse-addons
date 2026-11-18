"""Web page of the add-on (Home Assistant ingress): who is in control of each device."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("ilse_s2.web")

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ILSE S2 Gateway</title>
<style>
:root{--bg:#f4f5f2;--card:#fff;--fg:#1c2320;--mu:#5f6a64;--ln:#dde2dd;
--ilse:#0f6e56;--ilse-bg:#e1f3ec;--watch:#185fa5;--watch-bg:#e4f0fb;--ready:#534ab7;--ready-bg:#eceafb;
--taken:#9a5a00;--taken-bg:#fdf0d8;--bad:#a32d2d;--bat:#185fa5;--heat:#d85a30;--ev:#534ab7;--pv:#ba7517;
--f:"Segoe UI",system-ui,-apple-system,Roboto,sans-serif;--m:ui-monospace,"SFMono-Regular",Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#121614;--card:#1b201d;--fg:#e7ece9;--mu:#9ba69f;--ln:#2d3430;
--ilse:#5dcaa5;--ilse-bg:#0c3b2f;--watch:#85b7eb;--watch-bg:#0f2f50;--ready:#afa9ec;--ready-bg:#26215c;
--taken:#f2b552;--taken-bg:#40290a;--bad:#f09595;--bat:#85b7eb;--heat:#f0997b;--ev:#afa9ec;--pv:#ef9f27;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 var(--f)}
main{max-width:1060px;margin:0 auto;padding:20px 16px 40px;display:flex;flex-direction:column;gap:16px}
h1{font-size:22px;font-weight:600;margin:0}.mu{color:var(--mu);font-size:13px}
.top{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 16px}
.chip{font:500 12px var(--m);border:1px solid var(--ln);border-radius:6px;padding:2px 8px;background:var(--card)}
.banner{border-radius:12px;padding:14px 16px;display:flex;gap:12px;align-items:center;font-weight:600}
.banner svg{flex:none;width:26px;height:26px}
.b-taken{background:var(--taken-bg);color:var(--taken);border:1px solid var(--taken)}
.b-ilse{background:var(--ilse-bg);color:var(--ilse);border:1px solid color-mix(in srgb,var(--ilse) 40%,transparent)}
.b-ready{background:var(--ready-bg);color:var(--ready);border:1px solid color-mix(in srgb,var(--ready) 40%,transparent)}
.banner small{display:block;font-weight:400;color:var(--fg);opacity:.85}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--ln);border-radius:14px;padding:16px;display:flex;flex-direction:column;gap:14px;min-width:0}
.card.taken{border:2px solid var(--taken)}
.hd{display:flex;align-items:center;gap:12px}.hd svg.dev{width:56px;height:56px;flex:none;padding:6px;border-radius:14px;background:var(--bg)}
.hd .n{font-size:17px;font-weight:600}.hd .t{font:12px var(--m);color:var(--mu)}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;border-radius:999px;padding:4px 12px}
.pill i{width:8px;height:8px;border-radius:50%;background:currentColor}
.s-ilse{background:var(--ilse-bg);color:var(--ilse)}.s-watching{background:var(--watch-bg);color:var(--watch)}
.s-ready{background:var(--ready-bg);color:var(--ready)}.s-taken{background:var(--taken-bg);color:var(--taken)}
.s-taken i{animation:pulse 1.4s infinite}@keyframes pulse{50%{opacity:.25}}
@media (prefers-reduced-motion:reduce){.s-taken i{animation:none}}
.vals{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.v{background:var(--bg);border-radius:10px;padding:8px 10px}.v b{display:block;font-size:20px;font-weight:600;font-variant-numeric:tabular-nums}
.v span{font-size:12px;color:var(--mu)}
.soc{height:8px;border-radius:4px;background:var(--ln);overflow:hidden;margin-top:6px}.soc div{height:100%;background:var(--bat)}
.kv{display:grid;grid-template-columns:auto minmax(0,1fr);gap:2px 12px;font-size:13px}.kv dt{color:var(--mu)}.kv dd{margin:0;overflow-wrap:anywhere}
.last{border-left:3px solid var(--taken);padding:6px 10px;background:var(--taken-bg);border-radius:0;font-size:13px}
.tl{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px;max-height:260px;overflow:auto}
.tl li{display:grid;grid-template-columns:62px 14px minmax(0,1fr);gap:8px;font-size:13px;align-items:start}
.tl time{font:12px var(--m);color:var(--mu)}.dot{width:10px;height:10px;border-radius:50%;margin-top:5px}
.k-connect{background:var(--watch)}.k-control{background:var(--ready)}.k-instruction{background:var(--taken)}.k-disconnect{background:var(--mu)}
h2{font-size:13px;font-weight:600;color:var(--mu);margin:0;text-transform:uppercase;letter-spacing:.06em}
.foot{font-size:12px;color:var(--mu)}
</style></head><body><main>
<div class="top"><h1>S2 Gateway</h1><span class="chip" id="site">...</span><span class="chip" id="mode">shadow mode, read-only</span><span class="mu" id="upd"></span></div>
<div id="banner"></div>
<div class="grid" id="cards"></div>
<div class="foot">Each device is an S2 resource manager (EN 50491-12-2). In shadow mode instructions are received and logged but never executed; the energy manager receives them back as rejected.</div>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const hm=s=>s?new Date(s).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}):'';
function ago(s){if(!s)return'';const m=Math.round((Date.now()-new Date(s))/60000);return m<1?'just now':m<60?m+' min ago':Math.round(m/60)+' h ago'}
const SVG=(c,body)=>`<svg class="dev" viewBox="0 0 64 64" style="color:var(${c})">${body}</svg>`;
const ICON={
battery:SVG('--bat','<rect x="16" y="8" width="32" height="50" rx="4" fill="none" stroke="currentColor" stroke-width="2.5"/><rect x="26" y="4" width="12" height="5" rx="1.5" fill="currentColor"/><rect x="21" y="40" width="22" height="13" rx="2" fill="currentColor" opacity=".35"/><rect x="21" y="25" width="22" height="13" rx="2" fill="currentColor" opacity=".6"/><path d="M33 12 L27 22 H32 L30 30 L37 19 H32 L34 12 Z" fill="currentColor"/>'),
inverter:SVG('--bat','<rect x="14" y="6" width="36" height="46" rx="4" fill="none" stroke="currentColor" stroke-width="2.5"/><rect x="20" y="13" width="24" height="14" rx="2" fill="currentColor" opacity=".25"/><path d="M22 20 Q26 15 30 20 T38 20" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="24" cy="38" r="2.5" fill="currentColor"/><circle cx="32" cy="38" r="2.5" fill="currentColor" opacity=".5"/><path d="M20 52 V58 M44 52 V58" stroke="currentColor" stroke-width="2.5"/>'),
pv:SVG('--pv','<path d="M8 44 L16 14 H56 L48 44 Z" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/><path d="M29 14 L22 44 M42 14 L35 44 M12 29 H52" stroke="currentColor" stroke-width="1.8"/><path d="M26 52 H40 M33 44 V52" stroke="currentColor" stroke-width="2.5"/><circle cx="54" cy="8" r="4" fill="currentColor" opacity=".5"/>'),
charger:SVG('--ev','<rect x="12" y="6" width="22" height="48" rx="4" fill="none" stroke="currentColor" stroke-width="2.5"/><rect x="17" y="12" width="12" height="9" rx="1.5" fill="currentColor" opacity=".3"/><path d="M24 27 L20 34 H24 L22 40 L28 32 H24 L26 27 Z" fill="currentColor"/><path d="M34 22 H42 Q46 22 46 26 V44 Q46 48 50 48 H54" fill="none" stroke="currentColor" stroke-width="2.5"/><rect x="50" y="44" width="8" height="8" rx="2" fill="currentColor"/>'),
car:SVG('--ev','<path d="M6 40 L11 27 Q13 22 18 22 H44 Q49 22 51 27 L58 40 V48 H6 Z" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/><path d="M15 27 H49 L52 36 H12 Z" fill="currentColor" opacity=".2"/><circle cx="17" cy="48" r="5" fill="currentColor"/><circle cx="47" cy="48" r="5" fill="currentColor"/><path d="M33 26 L28 34 H33 L31 40 L38 31 H33 L35 26 Z" fill="currentColor"/>'),
boiler:SVG('--heat','<rect x="18" y="4" width="28" height="52" rx="12" fill="none" stroke="currentColor" stroke-width="2.5"/><path d="M32 20 C38 28 40 32 40 36 A8 8 0 0 1 24 36 C24 30 28 28 32 20 Z" fill="currentColor"/><path d="M24 58 V62 M40 58 V62" stroke="currentColor" stroke-width="2.5"/>'),
switch:SVG('--heat','<rect x="14" y="10" width="36" height="44" rx="8" fill="none" stroke="currentColor" stroke-width="2.5"/><circle cx="32" cy="32" r="9" fill="none" stroke="currentColor" stroke-width="2.5"/><path d="M32 20 V30" stroke="currentColor" stroke-width="2.5"/>')};
ICON.ev=ICON.car;
const WARN='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3 L22 20 H2 Z"/><path d="M12 10 V14 M12 17 V17.5"/></svg>';
const OK='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M8 12 L11 15 L16 9"/></svg>';
const fmtW=w=>w==null?'-':(Math.abs(w)>=1000?(w/1000).toFixed(2).replace(/\.?0+$/,'')+' kW':Math.round(w)+' W');
function card(d){
 const vals=[];
 if(d.type==='battery'||d.type==='ev'){vals.push(`<div class="v"><span>State of charge</span><b>${d.soc==null?'-':Math.round(d.soc)+'%'}</b><div class="soc"><div style="width:${d.soc??0}%"></div></div></div>`)}
 vals.push(`<div class="v"><span>Power now</span><b>${fmtW(d.power_w)}</b></div>`);
 vals.push(`<div class="v"><span>Instructions</span><b>${d.instructions}</b></div>`);
 const li=d.last_instruction;
 const last=li?`<div class="last"><b>Last instruction ${ago(li.received)}</b><br>${esc(Object.entries(li).filter(([k])=>['mode','power_w','factor'].includes(k)).map(([k,v])=>k.replace('_',' ')+' '+v).join(', '))} &middot; ${esc(li.status)}${li.shadow?' (shadow, not executed)':''}</div>`:'';
 const ev=[...(d.events||[])].reverse().map(e=>`<li><time>${hm(e.t)}</time><span class="dot k-${esc(e.kind)}"></span><span>${esc(e.text)}</span></li>`).join('');
 return `<section class="card ${d.state==='taken'?'taken':''}">
  <div class="hd">${ICON[d.icon]||ICON[d.type]||ICON.switch}<div><div class="n">${esc(d.name)}</div>${d.model?`<div class="mu">${esc(d.model)}</div>`:''}<div class="t">${esc(d.type)}${d.capacity_kwh?' &middot; '+d.capacity_kwh+' kWh':''}${d.rating_w?' &middot; '+fmtW(d.rating_w):''}</div></div></div>
  <div><span class="pill s-${esc(d.state)}"><i></i>${esc(d.label)}</span></div>
  <div class="vals">${vals.join('')}</div>
  <dl class="kv">${d.type==='ev'?`<dt>Car</dt><dd>${d.plugged_in?'plugged in':'not plugged in'}</dd><dt>Target</dt><dd>${esc(d.target||'none')}</dd>`:''}<dt>S2 control type</dt><dd>${esc(d.control_type||'none')}</dd><dt>Connected since</dt><dd>${d.connected_since?hm(d.connected_since)+' ('+ago(d.connected_since)+')':'not connected'}</dd><dt>Resource id</dt><dd style="font-family:var(--m);font-size:12px">${esc(d.rm_id)}</dd></dl>
  ${last}
  <div><h2>Timeline</h2><ul class="tl">${ev||'<li><time></time><span></span><span class="mu">nothing yet</span></li>'}</ul></div>
 </section>`}
async function load(){
 let st;try{st=await (await fetch('api/state',{cache:'no-store'})).json()}catch(e){$('upd').textContent='gateway not reachable';return}
 $('site').textContent=st.site;$('upd').textContent='updated '+hm(st.now);
 const taken=st.devices.filter(d=>d.state==='taken'),ready=st.devices.filter(d=>d.state==='ready');
 $('banner').innerHTML=taken.length?`<div class="banner b-taken">${WARN}<div>External energy manager has taken control of ${taken.map(d=>esc(d.name)).join(' and ')}<small>Energy manager: ${esc(st.cem)}. Shadow mode: instructions are logged, not executed.</small></div></div>`
  :ready.length?`<div class="banner b-ready">${OK}<div>External energy manager connected and allowed to steer ${ready.map(d=>esc(d.name)).join(' and ')}<small>Energy manager: ${esc(st.cem)}. No instruction in the last 15 minutes.</small></div></div>`
  :`<div class="banner b-ilse">${OK}<div>ILSE is in control of all devices<small>No external energy manager is steering.</small></div></div>`;
 $('cards').innerHTML=st.devices.map(card).join('')}
load();setInterval(load,5000);
</script></main></body></html>"""


def serve(gw, port: int = 8099) -> None:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?")[0].rstrip("/")
            if path.endswith("/api/state") or path == "api/state":
                self._send(200, json.dumps(gw.view(), default=str).encode(), "application/json")
            else:
                self._send(200, PAGE.encode(), "text/html; charset=utf-8")

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True, name="web").start()
    log.info("web page on :%s (Home Assistant ingress)", port)
