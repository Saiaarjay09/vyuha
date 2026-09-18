"""The web console, as a single self-contained page.

No build step, no framework, no CDN. One file that a browser can render and a
human can read -- which matters for a risk tool, because you should be able to
audit the thing that is showing you numbers.
"""

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vyuha</title>
<style>
:root{
  --bg:#0b0e14; --panel:#11151f; --panel2:#161b28; --line:#232a3a;
  --fg:#d7dce8; --dim:#7c8699; --dimmer:#4f5870;
  --accent:#6ea8fe; --good:#5ad19a; --warn:#e8b84b; --bad:#f26b6b;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--mono);
  font-size:14px;line-height:1.55;display:flex;flex-direction:column}
a{color:var(--accent)}
header{border-bottom:1px solid var(--line);padding:10px 16px;display:flex;
  align-items:baseline;gap:12px;flex-wrap:wrap;background:var(--panel)}
header h1{margin:0;font-size:15px;letter-spacing:.14em;font-weight:600}
header .sub{color:var(--dim);font-size:12px}
header .status{margin-left:auto;font-size:12px;color:var(--dim)}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;
  background:var(--dimmer);margin-right:6px;vertical-align:middle}
.dot.on{background:var(--good)} .dot.off{background:var(--bad)}

main{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:14px}
.wrap{width:100%;max-width:880px;margin:0 auto}

.msg{white-space:pre-wrap;word-break:break-word}
.msg.user{color:var(--fg)}
.msg.user .p{color:var(--accent)}
.msg.sys{color:var(--dim);font-size:13px}
.msg.err{color:var(--bad)}

.card{border:1px solid var(--line);border-radius:6px;background:var(--panel);
  padding:14px;margin-top:6px}
.card h3{margin:0 0 10px;font-size:12px;letter-spacing:.1em;color:var(--dim);
  text-transform:uppercase;font-weight:600}

.verdict{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;
  padding-bottom:10px;border-bottom:1px solid var(--line);margin-bottom:12px}
.verdict .pct{font-size:34px;font-weight:600;letter-spacing:-.02em}
.verdict .lbl{color:var(--dim);font-size:12px}

.bar{height:5px;background:var(--panel2);border-radius:3px;overflow:hidden;margin-top:3px}
.bar i{display:block;height:100%;background:var(--accent)}

.mem{display:grid;grid-template-columns:132px 54px 1fr;gap:10px;align-items:center;
  padding:6px 0;border-bottom:1px solid #1a2030}
.mem:last-child{border-bottom:none}
.mem .n{color:var(--fg);font-size:13px;overflow:hidden;text-overflow:ellipsis}
.mem .v{text-align:right;font-variant-numeric:tabular-nums;font-size:13px}
.mem .why{grid-column:1/-1;color:var(--dim);font-size:12px;margin:-2px 0 4px}
.mem .cite{color:var(--dimmer);font-size:11px}

.ev{display:grid;grid-template-columns:auto 1fr auto;gap:8px 12px;font-size:12.5px}
.ev .id{color:var(--dimmer)}
.ev .lb{color:var(--dim)}
.ev .vl{text-align:right;font-variant-numeric:tabular-nums}

.note{color:var(--dim);font-size:12px;margin-top:10px;padding-top:10px;
  border-top:1px solid var(--line);white-space:pre-wrap}
.warn{border-left:2px solid var(--warn);padding-left:10px;color:var(--warn);
  font-size:12.5px;margin:10px 0}
.dissent{border-left:2px solid var(--dim);padding-left:10px;margin:8px 0;
  color:var(--fg);font-size:12.5px}

footer{border-top:1px solid var(--line);background:var(--panel);padding:10px 16px}
form{display:flex;gap:10px;align-items:flex-start;max-width:880px;margin:0 auto;width:100%}
.prompt{color:var(--accent);padding-top:7px}
textarea{flex:1;background:var(--panel2);border:1px solid var(--line);color:var(--fg);
  font-family:var(--mono);font-size:14px;padding:7px 10px;border-radius:5px;
  resize:none;min-height:36px;max-height:160px;outline:none}
textarea:focus{border-color:var(--accent)}
button{background:var(--accent);color:#0b0e14;border:0;border-radius:5px;
  padding:8px 16px;font-family:var(--mono);font-weight:600;cursor:pointer;font-size:13px}
button:disabled{opacity:.45;cursor:not-allowed}
.hint{max-width:880px;margin:8px auto 0;color:var(--dimmer);font-size:11.5px}

.spin::after{content:"";animation:d 1.2s steps(4,end) infinite}
@keyframes d{0%{content:""}25%{content:"."}50%{content:".."}75%{content:"..."}}
@media(max-width:640px){
  .mem{grid-template-columns:100px 48px 1fr}
  .verdict .pct{font-size:28px}
  header .status{width:100%;margin-left:0}
}
</style>
</head>
<body>
<header>
  <h1>VYUHA</h1>
  <span class="sub">Indian markets &middot; bias-diverse council</span>
  <span class="status"><span class="dot" id="dot"></span><span id="st">connecting</span></span>
</header>

<main id="log"><div class="wrap" id="logw"></div></main>

<footer>
  <form id="f">
    <span class="prompt">&gt;</span>
    <textarea id="q" rows="1" placeholder="Ask a question — e.g. Will the Nifty 50 close below 22,900 in the next 30 days?" autofocus></textarea>
    <button id="go" type="submit">Ask</button>
  </form>
  <div class="hint">Enter to send &middot; Shift+Enter for newline &middot; /help /evidence /personas /sources</div>
</footer>

<script>
// Works whether the app is mounted at / or behind a reverse-proxy subpath
// (Tailscale serve --set-path=/vyuha), so the same page serves both.
const BASE=location.pathname.replace(/\/+$/,'');
const api=p=>BASE+p;

const logw=document.getElementById('logw'), form=document.getElementById('f'),
      qEl=document.getElementById('q'), go=document.getElementById('go'),
      dot=document.getElementById('dot'), st=document.getElementById('st');
let busy=false;

const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pct=v=>v==null?'—':(v*100).toFixed(1)+'%';
const num=v=>typeof v==='number'?v.toLocaleString('en-IN',{maximumFractionDigits:4}):esc(v);

function add(html,cls){const d=document.createElement('div');d.className='msg '+(cls||'');
  d.innerHTML=html;logw.appendChild(d);
  document.getElementById('log').scrollTop=1e9;return d;}

function colorFor(p){return p==null?'var(--dim)':p>=.66?'var(--bad)':p>=.33?'var(--warn)':'var(--good)';}

async function health(){
  try{
    const r=await fetch(api('/api/health')),d=await r.json();
    dot.className='dot on';
    const fam=d.distinct_model_families||0;
    st.textContent=`v${d.version} · ${d.models.length} model${d.models.length===1?'':'s'}`+
      (fam<2?' · correlated':'');
  }catch(e){dot.className='dot off';st.textContent='offline';}
}

function renderCouncil(d){
  let h='<div class="card">';
  h+=`<div class="verdict"><div><div class="pct" style="color:${colorFor(d.probability)}">${pct(d.probability)}</div>`;
  h+=`<div class="lbl">probability · resolves ${esc(d.resolves)}</div></div>`;
  h+=`<div><div class="lbl">dispersion</div><div>${d.dispersion?.toFixed(3)??'—'}</div></div>`;
  h+=`<div><div class="lbl">members</div><div>${d.n_members}</div></div></div>`;

  if(d.independence_warning) h+=`<div class="warn">⚠ ${esc(d.independence_warning)}</div>`;

  h+='<h3>Members</h3>';
  for(const m of d.members){
    if(!m.ok){h+=`<div class="mem"><span class="n">${esc(m.name)}</span>
      <span class="v" style="color:var(--bad)">fail</span>
      <span class="cite">${esc(m.error||'')}</span></div>`;continue;}
    h+=`<div class="mem"><span class="n">${esc(m.name)}</span>
      <span class="v">${pct(m.probability)}</span>
      <span><span class="bar"><i style="width:${(m.probability*100).toFixed(1)}%;background:${colorFor(m.probability)}"></i></span></span>`;
    if(m.reasoning) h+=`<div class="why">${esc(m.reasoning)}</div>`;
    h+=`<div class="cite">cites ${m.citations.length?esc(m.citations.join(', ')):'nothing'} · ${esc(m.model)}</div></div>`;
  }

  if(d.dissent?.length){h+='<h3 style="margin-top:14px">Dissent</h3>';
    for(const x of d.dissent) h+=`<div class="dissent">${esc(x)}</div>`;}
  if(d.counterargument) h+=`<h3 style="margin-top:14px">Strongest counterargument</h3>
    <div class="dissent">${esc(d.counterargument)}</div>`;

  if(d.evidence?.length){
    h+='<h3 style="margin-top:14px">Evidence used</h3><div class="ev">';
    for(const e of d.evidence)
      h+=`<span class="id">${esc(e.id)}</span><span class="lb">${esc(e.label)}</span><span class="vl">${num(e.value)}</span>`;
    h+='</div>';
  }
  for(const c of (d.evidence_caveats||[])) h+=`<div class="warn">${esc(c)}</div>`;
  if(d.notes?.length) h+=`<div class="note">${esc(d.notes.join('\n'))}</div>`;
  h+=`<div class="note">This is calibrated uncertainty, not a prediction. Dispersion is part of the answer — a tight consensus from correlated models is not evidence.</div>`;
  return h+'</div>';
}

function renderData(d){
  let h='<div class="card"><h3>Live values'+(d.exact_match?'':' — no exact match, showing everything')+'</h3><div class="ev">';
  for(const m of d.matches)
    h+=`<span class="id">${esc(m.source)}</span><span class="lb">${esc(m.label)}</span><span class="vl">${num(m.value)} ${esc(m.unit||'')}</span>`;
  h+='</div>';
  for(const c of (d.caveats||[])) h+=`<div class="warn">${esc(c)}</div>`;
  return h+`<div class="note">${esc(d.note)} · as of ${esc(d.as_of)}</div></div>`;
}

function renderRisk(d){
  let h='<div class="card"><h3>Stress scenarios</h3><div class="ev">';
  for(const s of d.scenarios)
    h+=`<span class="id"></span><span class="lb">${esc(s.name)}</span><span class="vl" style="color:${s.pnl_pct<-0.2?'var(--bad)':s.pnl_pct<-0.05?'var(--warn)':'var(--fg)'}">${(s.pnl_pct*100).toFixed(1)}% · ₹${s.pnl_inr_cr} cr</span>`;
  h+='</div>';
  if(d.unmodelled_exposures?.length)
    h+=`<div class="warn">⚠ Unmodelled exposure, treated as zero: ${esc(d.unmodelled_exposures.join(', '))}</div>`;
  return h+`<div class="note">${esc(d.note)}</div></div>`;
}

async function showList(path,fmt){
  const r=await fetch(api(path)),d=await r.json();add(fmt(d),'sys');
}

const HELP=`Vyuha — an open risk engine for Indian markets.

Ask a forecastable question and a council of ten deliberately-biased models
answers with a calibrated probability, the evidence each member cited, and the
disagreement between them.

  Will the Nifty 50 close below 22,900 in the next 30 days?
  What is the repo rate?
  Stress test a large-cap heavy book

Commands
  /help        this
  /evidence    live evidence packet the council is reasoning from
  /personas    the ten members and the bias each argues from
  /sources     data source catalogue and what is verified working

The precision limits are documented — no system can resolve 0.00001% moves;
that is below NSE tick size. See docs/PRECISION.md in the repo.`;

async function submit(text){
  if(busy)return; busy=true; go.disabled=true;
  add(`<span class="p">&gt;</span> ${esc(text)}`,'user');

  const cmd=text.trim().toLowerCase();
  try{
    if(cmd==='/help'){add(esc(HELP),'sys');return;}
    if(cmd==='/evidence'){
      return showList('/api/evidence',d=>{
        let h='<div class="card"><h3>Evidence packet · '+esc(d.fingerprint)+'</h3><div class="ev">';
        for(const e of d.items) h+=`<span class="id">${esc(e.id)}</span><span class="lb">${esc(e.label)}</span><span class="vl">${num(e.value)} ${esc(e.unit||'')}</span>`;
        h+='</div>';
        for(const c of (d.caveats||[])) h+=`<div class="warn">${esc(c)}</div>`;
        return h+`<div class="note">as of ${esc(d.as_of)}</div></div>`;});
    }
    if(cmd==='/personas'){
      return showList('/api/personas',d=>{
        let h='<div class="card"><h3>Council</h3>';
        for(const p of d) h+=`<div style="margin-bottom:10px"><b>${esc(p.name)}</b> — ${esc(p.title)}
          <div class="cite">${esc(p.bias)}</div></div>`;
        return h+'</div>';});
    }
    if(cmd==='/sources'){
      return showList('/api/sources',d=>{
        const s=d.summary;
        let h=`<div class="card"><h3>Sources — ${s.working} working · ${s.fragile} fragile · ${s.blocked} blocked · ${s.planned} planned</h3><div class="ev">`;
        for(const x of d.sources.filter(x=>x.status!=='planned'))
          h+=`<span class="id" style="color:${x.status==='working'?'var(--good)':x.status==='blocked'?'var(--bad)':'var(--warn)'}">${esc(x.status)}</span><span class="lb">${esc(x.name)}</span><span class="vl">${esc(x.verified||'—')}</span>`;
        return h+`</div><div class="note">${s.planned} more catalogued but not yet wired.</div></div>`;});
    }

    const pending=add('<span class="spin">thinking</span>','sys');
    const r=await fetch(api('/api/ask/stream'),{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({question:text,rounds:2,horizon_days:30})});
    if(!r.ok) throw new Error('HTTP '+r.status);

    const rd=r.body.getReader(),dec=new TextDecoder();let buf='';
    while(true){
      const{done,value}=await rd.read(); if(done)break;
      buf+=dec.decode(value,{stream:true});
      const parts=buf.split('\n\n'); buf=parts.pop();
      for(const p of parts){
        const ev=(p.match(/^event: (.+)$/m)||[])[1];
        const dl=(p.match(/^data: ([\s\S]+)$/m)||[])[1];
        if(!ev||!dl)continue;
        let d; try{d=JSON.parse(dl)}catch(e){continue}
        if(ev==='status'){
          let s=d.stage;
          if(d.members) s+=` — ${d.members.join(', ')}`;
          pending.innerHTML=`<span class="spin">${esc(s)}</span>`;
        } else if(ev==='error'){
          pending.className='msg err';pending.textContent='Error: '+d.error;
        } else if(ev==='done'){
          pending.remove();
          add(d.route==='council'?renderCouncil(d):d.route==='data'?renderData(d):renderRisk(d));
        }
      }
    }
  }catch(e){add('Error: '+esc(e.message),'err');}
  finally{busy=false;go.disabled=false;qEl.focus();}
}

form.addEventListener('submit',e=>{e.preventDefault();
  const t=qEl.value.trim(); if(!t)return; qEl.value=''; qEl.style.height='auto'; submit(t);});
qEl.addEventListener('keydown',e=>{
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();form.requestSubmit();}});
qEl.addEventListener('input',()=>{qEl.style.height='auto';
  qEl.style.height=Math.min(qEl.scrollHeight,160)+'px';});

health(); setInterval(health,30000);
add(esc(HELP),'sys');
</script>
</body>
</html>
"""
