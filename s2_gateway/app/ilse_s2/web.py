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
--taken:#9a5a00;--taken-bg:#fdf0d8;--bad:#a32d2d;--bat:#185fa5;--heat:#d85a30;
--f:"Segoe UI",system-ui,-apple-system,Roboto,sans-serif;--m:ui-monospace,"SFMono-Regular",Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#121614;--card:#1b201d;--fg:#e7ece9;--mu:#9ba69f;--ln:#2d3430;
--ilse:#5dcaa5;--ilse-bg:#0c3b2f;--watch:#85b7eb;--watch-bg:#0f2f50;--ready:#afa9ec;--ready-bg:#26215c;
--taken:#f2b552;--taken-bg:#40290a;--bad:#f09595;--bat:#85b7eb;--heat:#f0997b;color-scheme:dark}}
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
.hd{display:flex;align-items:center;gap:12px}.hd svg.dev{width:40px;height:40px;flex:none}
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
const ICON={
battery:'<svg class="dev" viewBox="0 0 40 40" style="color:var(--bat)"><rect x="5" y="11" width="27" height="18" rx="3" fill="none" stroke="currentColor" stroke-width="2.4"/><rect x="32" y="16" width="4" height="8" rx="1" fill="currentColor"/><path d="M19 14 L14 21 H19 L17 26 L24 19 H19 L21 14 Z" fill="currentColor"/></svg>',
switch:'<svg class="dev" viewBox="0 0 40 40" style="color:var(--heat)"><rect x="11" y="4" width="18" height="32" rx="7" fill="none" stroke="currentColor" stroke-width="2.4"/><path d="M20 14 C24 19 25 22 25 24 A5 5 0 0 1 15 24 C15 20 18 19 20 14 Z" fill="currentColor"/></svg>'};
const WARN='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3 L22 20 H2 Z"/><path d="M12 10 V14 M12 17 V17.5"/></svg>';
const OK='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M8 12 L11 15 L16 9"/></svg>';
const fmtW=w=>w==null?'-':(Math.abs(w)>=1000?(w/1000).toFixed(2).replace(/\.?0+$/,'')+' kW':Math.round(w)+' W');
function card(d){
 const vals=[];
 if(d.type==='battery'){vals.push(`<div class="v"><span>State of charge</span><b>${d.soc==null?'-':Math.round(d.soc)+'%'}</b><div class="soc"><div style="width:${d.soc??0}%"></div></div></div>`)}
 vals.push(`<div class="v"><span>Power now</span><b>${fmtW(d.power_w)}</b></div>`);
 vals.push(`<div class="v"><span>Instructions</span><b>${d.instructions}</b></div>`);
 const li=d.last_instruction;
 const last=li?`<div class="last"><b>Last instruction ${ago(li.received)}</b><br>${esc(Object.entries(li).filter(([k])=>['mode','power_w','factor'].includes(k)).map(([k,v])=>k.replace('_',' ')+' '+v).join(', '))} &middot; ${esc(li.status)}${li.shadow?' (shadow, not executed)':''}</div>`:'';
 const ev=[...(d.events||[])].reverse().map(e=>`<li><time>${hm(e.t)}</time><span class="dot k-${esc(e.kind)}"></span><span>${esc(e.text)}</span></li>`).join('');
 return `<section class="card ${d.state==='taken'?'taken':''}">
  <div class="hd">${ICON[d.type]||ICON.switch}<div><div class="n">${esc(d.name)}</div><div class="t">${esc(d.type)}${d.capacity_kwh?' &middot; '+d.capacity_kwh+' kWh':''}${d.rating_w?' &middot; '+fmtW(d.rating_w):''}</div></div></div>
  <div><span class="pill s-${esc(d.state)}"><i></i>${esc(d.label)}</span></div>
  <div class="vals">${vals.join('')}</div>
  <dl class="kv"><dt>S2 control type</dt><dd>${esc(d.control_type||'none')}</dd><dt>Connected since</dt><dd>${d.connected_since?hm(d.connected_since)+' ('+ago(d.connected_since)+')':'not connected'}</dd><dt>Resource id</dt><dd style="font-family:var(--m);font-size:12px">${esc(d.rm_id)}</dd></dl>
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
