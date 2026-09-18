"""The web console.

Written for someone who has never used a risk system. The hard numbers are all
still here, but the front of the page is plain English and everything
technical is one click away rather than in your face.

Three rules the design follows:
  - Say the answer in words before saying it as a number.
  - Never show a term without explaining it in the same breath.
  - Never hide the uncertainty to look more confident.
"""

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vyuha</title>
<style>
:root{
  --bg:#fbfbfa; --card:#fff; --line:#e6e4e0; --line2:#f0eeeb;
  --fg:#1c1b19; --dim:#6b6862; --dimmer:#9a968e;
  --accent:#2d6cdf; --accent-soft:#eef3fd;
  --no:#2e9e6b; --mid:#c9891f; --yes:#d4553d;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif;
  --num:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#16161a; --card:#1d1d22; --line:#2c2c33; --line2:#26262c;
  --fg:#eceaea; --dim:#a3a09b; --dimmer:#6e6b66;
  --accent:#6fa0f5; --accent-soft:#1e2739;
  --no:#54c08c; --mid:#e0a63f; --yes:#ef7a60;
}}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--sans);
  font-size:16px;line-height:1.6;display:flex;flex-direction:column;
  -webkit-font-smoothing:antialiased}

header{padding:18px 20px 14px;border-bottom:1px solid var(--line);background:var(--card)}
.hdr{max-width:680px;margin:0 auto;display:flex;align-items:center;gap:10px}
.hdr h1{margin:0;font-size:17px;font-weight:650;letter-spacing:-.01em}
.hdr .tag{color:var(--dim);font-size:14px}
.hdr .st{margin-left:auto;font-size:12.5px;color:var(--dimmer)}

main{flex:1;overflow-y:auto;padding:22px 20px 8px}
.wrap{max-width:680px;margin:0 auto;display:flex;flex-direction:column;gap:18px}

.intro h2{margin:0 0 8px;font-size:21px;font-weight:650;letter-spacing:-.01em}
.intro p{margin:0 0 12px;color:var(--dim);font-size:15px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;
  padding:8px 14px;font-size:14px;cursor:pointer;color:var(--fg);
  font-family:inherit;text-align:left;transition:border-color .12s,background .12s}
.chip:hover{border-color:var(--accent);background:var(--accent-soft)}

.you{align-self:flex-end;background:var(--accent);color:#fff;padding:10px 15px;
  border-radius:16px 16px 4px 16px;max-width:85%;font-size:15px}

.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:20px;overflow:hidden}

.headline{font-size:24px;font-weight:650;letter-spacing:-.02em;margin:0 0 4px}
.sub{color:var(--dim);font-size:14.5px;margin:0}
.meter{height:8px;background:var(--line2);border-radius:99px;margin:16px 0 6px;overflow:hidden}
.meter i{display:block;height:100%;border-radius:99px;transition:width .5s ease}
.scale{display:flex;justify-content:space-between;color:var(--dimmer);font-size:12px}

.agree{margin-top:16px;padding:12px 14px;background:var(--bg);
  border-radius:10px;font-size:14.5px;color:var(--fg)}
.agree b{font-weight:600}
.agree span{color:var(--dim)}

.qa{margin-top:16px;padding-top:14px;border-top:1px solid var(--line2)}
.qa h4{margin:0 0 4px;font-size:14px;font-weight:600}
.qa p{margin:0 0 12px;color:var(--dim);font-size:14.5px}

details{margin-top:10px;border-top:1px solid var(--line2);padding-top:10px}
details summary{cursor:pointer;font-size:14px;color:var(--accent);
  list-style:none;user-select:none;padding:3px 0}
details summary::-webkit-details-marker{display:none}
details summary::before{content:"› ";display:inline-block;transition:transform .15s}
details[open] summary::before{transform:rotate(90deg)}
details .body{padding:10px 0 4px}

.person{display:flex;gap:12px;align-items:flex-start;padding:11px 0;
  border-bottom:1px solid var(--line2)}
.person:last-child{border-bottom:none}
.person .pct{font-family:var(--num);font-size:14px;font-weight:600;min-width:44px;
  text-align:right;padding-top:1px}
.person .who{flex:1;min-width:0}
.person .nm{font-size:14.5px;font-weight:600}
.person .rl{font-size:13px;color:var(--dimmer);margin-bottom:3px}
.person .sy{font-size:14px;color:var(--dim)}

.rows{display:flex;flex-direction:column;gap:2px}
.row{display:flex;gap:12px;align-items:baseline;padding:5px 0;
  border-bottom:1px solid var(--line2);font-size:14.5px}
.row:last-child{border-bottom:none}
.row .k{color:var(--dim);flex:1}
.row .v{white-space:nowrap}
.row .v{font-family:var(--num);font-weight:600}

.flag{margin-top:14px;padding:12px 14px;border-radius:10px;font-size:14px;
  background:#fdf6e8;color:#7a5a12;border:1px solid #f0e0bd}
@media (prefers-color-scheme:dark){.flag{background:#2b2513;color:#e6c675;border-color:#463c1e}}

.foot{color:var(--dimmer);font-size:13px;margin-top:16px;padding-top:12px;
  border-top:1px solid var(--line2)}
.sys{color:var(--dim);font-size:14.5px;white-space:pre-wrap}
.err{color:var(--yes);font-size:14.5px}
.load{color:var(--dim);font-size:14.5px}
.load::after{content:"";animation:d 1.3s steps(4,end) infinite}
@keyframes d{0%{content:""}25%{content:"."}50%{content:".."}75%{content:"..."}}

footer{position:sticky;bottom:0;background:var(--card);border-top:1px solid var(--line);
  padding:14px 20px 16px}
form{display:flex;gap:10px;max-width:680px;margin:0 auto;align-items:flex-end}
textarea{flex:1;font-family:inherit;font-size:16px;padding:12px 14px;
  border:1px solid var(--line);border-radius:12px;background:var(--bg);color:var(--fg);
  resize:none;min-height:46px;max-height:150px;outline:none;line-height:1.45}
textarea:focus{border-color:var(--accent)}
button.go{background:var(--accent);color:#fff;border:0;border-radius:12px;
  padding:0 20px;height:46px;font-size:15px;font-weight:600;cursor:pointer;
  font-family:inherit;flex-shrink:0}
button.go:disabled{opacity:.4;cursor:not-allowed}
.tip{max-width:680px;margin:9px auto 0;color:var(--dimmer);font-size:12.5px;text-align:center}

@media(max-width:600px){
  body{font-size:15px}
  .headline{font-size:21px}
  main{padding:18px 16px 8px}
  header,footer{padding-left:16px;padding-right:16px}
}
</style>
</head>
<body>

<header><div class="hdr">
  <h1>Vyuha</h1><span class="tag">Indian markets, explained</span>
  <span class="st" id="st">·</span>
</div></header>

<main><div class="wrap" id="log"></div></main>

<footer>
  <form id="f">
    <textarea id="q" rows="1" placeholder="Ask anything about Indian markets…"></textarea>
    <button class="go" id="go" type="submit">Ask</button>
  </form>
  <div class="tip">Free and open source · Not investment advice</div>
</footer>

<script>
const BASE=location.pathname.replace(/\/+$/,''), api=p=>BASE+p;
const log=document.getElementById('log'), form=document.getElementById('f'),
      qEl=document.getElementById('q'), go=document.getElementById('go'),
      stEl=document.getElementById('st');
let busy=false;

const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=v=>typeof v==='number'?v.toLocaleString('en-IN',{maximumFractionDigits:2}):esc(v);

/* ---------- turning numbers into plain English ---------- */
function verdict(p){
  if(p<0.10) return['Very unlikely','var(--no)'];
  if(p<0.30) return['Unlikely','var(--no)'];
  if(p<0.45) return['Probably not','var(--mid)'];
  if(p<0.55) return['Too close to call','var(--mid)'];
  if(p<0.70) return['Fairly likely','var(--mid)'];
  if(p<0.90) return['Likely','var(--yes)'];
  return['Very likely','var(--yes)'];
}
function odds(p){
  if(p<=0||p>=1) return '';
  const n=Math.round(1/(p<0.5?p:1-p));
  if(n<2||n>200) return '';
  return p<0.5?`roughly a 1 in ${n} chance`:`roughly a ${n-1} in ${n} chance`;
}
function agreement(d,n){
  if(n<2) return['',''];
  if(d<0.05) return['They nearly all agreed.','That is a strong signal — but see the note below about why agreement can mislead.'];
  if(d<0.12) return['They mostly agreed.','A few advisors leaned differently, but there was no real split.'];
  if(d<0.22) return['They partly disagreed.','Treat this answer as a rough guide rather than a firm number.'];
  return['They disagreed a lot.','There is no reliable answer here. The disagreement is the finding.'];
}
const LABELS={
  REPO_RATE:'Repo rate (RBI policy rate)', SDF_RATE:'Standing deposit facility',
  MSF_RATE:'Marginal standing facility', BANK_RATE:'Bank rate',
  REVERSE_REPO_RATE:'Reverse repo rate', CRR:'Cash reserve ratio (CRR)',
  SLR:'Statutory liquidity ratio (SLR)', USDINR:'Rupees per US dollar',
  GBPINR:'Rupees per British pound', EURINR:'Rupees per euro',
  JPYINR_100:'Rupees per 100 yen', NIFTY_50:'Nifty 50 index',
  NIFTY_BANK:'Bank Nifty index', INDIA_VIX:'India VIX (fear gauge)',
  NIFTY_MIDCAP_100:'Nifty Midcap 100 index',
  DII_NET_CASH:'Indian institutions bought (net)',
  FII_FPI_NET_CASH:'Foreign investors bought (net)',
  NIFTY_PUT_CALL_RATIO:'Put-call ratio (bearish if high)',
  NIFTY_ATM_IV:'Expected volatility from options',
  US10Y:'US 10-year bond yield', BRENT:'Brent crude oil'
};
const nice=k=>LABELS[k]||k.replace(/_/g,' ').toLowerCase()
  .replace(/^./,c=>c.toUpperCase());

const ROLES={
  hawk:'Worries about inflation', dove:'Worries about weak growth',
  value_bear:'Thinks shares are overpriced', momentum_bull:'Follows the trend',
  global_macro:'Watches the US, the dollar and oil', flows:'Watches who is buying and selling',
  quant:'Only trusts the numbers', policy:'Watches the government and RBI',
  behavioural:'Watches the mood of the crowd', red_team:'Argues against everyone else'
};

function add(html,cls){const d=document.createElement('div');
  if(cls)d.className=cls; d.innerHTML=html; log.appendChild(d);
  d.scrollIntoView({block:'nearest'}); return d;}

/* ---------- renderers ---------- */
function renderCouncil(d){
  const p=d.probability, [word,col]=verdict(p), o=odds(p);
  const [agTitle,agBody]=agreement(d.dispersion,d.n_members);
  const ok=d.members.filter(m=>m.ok);

  let h=`<div class="card">
    <p class="headline" style="color:${col}">${word}</p>
    <p class="sub">There is about a <b>${(p*100).toFixed(0)}% chance</b> of this happening${o?' — '+o:''}.</p>
    <div class="meter"><i style="width:${Math.max(p*100,1.5)}%;background:${col}"></i></div>
    <div class="scale"><span>Won't happen</span><span>Will happen</span></div>`;

  if(agTitle) h+=`<div class="agree"><b>${esc(agTitle)}</b> <span>${esc(agBody)}</span></div>`;
  if(d.independence_warning)
    h+=`<div class="flag"><b>Worth knowing:</b> every advisor here is powered by the
        same AI model, so they tend to make the same mistakes. Their agreement means
        less than it looks. Installing more models fixes this.</div>`;

  h+=`<div class="qa"><h4>What this actually means</h4>
      <p>${esc(d.n_members)} AI advisors, each deliberately given a different outlook,
      looked at today's live market data and each gave their own estimate. The number
      above combines them. It is a considered guess, not a prediction — nobody can
      predict markets.</p></div>`;

  h+=`<details><summary>See what each advisor said</summary><div class="body">`;
  for(const m of ok){
    const [w,c]=verdict(m.probability);
    h+=`<div class="person">
      <span class="pct" style="color:${c}">${(m.probability*100).toFixed(0)}%</span>
      <span class="who"><span class="nm">${esc(m.name.replace(/_/g,' '))}</span>
      <div class="rl">${esc(ROLES[m.name]||'')}</div>
      ${m.reasoning?`<div class="sy">${esc(m.reasoning)}</div>`:''}</span></div>`;
  }
  const bad=d.members.length-ok.length;
  if(bad) h+=`<p class="sub" style="margin-top:10px">${bad} advisor${bad>1?'s':''} failed to answer and ${bad>1?'were':'was'} left out.</p>`;
  h+=`</div></details>`;

  if(d.dissent?.length||d.counterargument){
    h+=`<details><summary>See the strongest argument against this answer</summary><div class="body">`;
    if(d.counterargument) h+=`<p class="sub">${esc(d.counterargument)}</p>`;
    h+=`</div></details>`;
  }

  if(d.evidence?.length){
    h+=`<details><summary>See the ${d.evidence.length} facts they used</summary><div class="body"><div class="rows">`;
    for(const e of d.evidence)
      h+=`<div class="row"><span class="k">${esc(nice(e.label))}</span><span class="v">${fmt(e.value)}</span></div>`;
    h+=`</div><p class="sub" style="margin-top:10px">All figures pulled live from the
        RBI, the NSE and public data sources. Advisors may only use these — they are
        not allowed to invent numbers.</p></div></details>`;
  }

  h+=`<details><summary>Technical details</summary><div class="body">
      <div class="rows">
        <div class="row"><span class="k">Combined probability</span><span class="v">${(p*100).toFixed(2)}%</span></div>
        <div class="row"><span class="k">Spread between advisors</span><span class="v">${d.dispersion?.toFixed(3)??'—'}</span></div>
        <div class="row"><span class="k">Advisors answering</span><span class="v">${d.n_members}</span></div>
        <div class="row"><span class="k">Resolves on</span><span class="v">${esc(d.resolves)}</span></div>
      </div>
      <p class="sub" style="margin-top:10px;white-space:pre-wrap">${esc((d.notes||[]).join('\n'))}</p>
      </div></details>`;

  return h+`<p class="foot">This is an estimate of uncertainty, not advice. Do not
    make financial decisions from it.</p></div>`;
}

function renderData(d){
  let h=`<div class="card"><p class="headline">Live figures</p>
    <p class="sub">Read straight from the source. No AI involved, nothing estimated.</p>
    <div class="rows" style="margin-top:14px">`;
  for(const m of d.matches.slice(0,14))
    h+=`<div class="row"><span class="k">${esc(nice(m.label))}</span>
        <span class="v">${fmt(m.value)}${m.unit==='pct'?'%':m.unit==='INR'?'':m.unit?' '+esc(m.unit):''}</span></div>`;
  h+=`</div>`;
  if(!d.exact_match) h+=`<p class="sub" style="margin-top:12px">Couldn't match that exactly, so here's everything currently available.</p>`;
  return h+`<p class="foot">Source: RBI and NSE, fetched just now.</p></div>`;
}

function renderRisk(d){
  let h=`<div class="card"><p class="headline">If history repeated</p>
    <p class="sub">What an example portfolio would lose in each of these real past
    crises. This uses a sample portfolio, not yours.</p><div class="rows" style="margin-top:14px">`;
  for(const s of d.scenarios.slice(0,7)){
    const c=s.pnl_pct<-0.3?'var(--yes)':s.pnl_pct<-0.1?'var(--mid)':'var(--fg)';
    h+=`<div class="row"><span class="k">${esc(s.name)}</span>
        <span class="v" style="color:${c}">${(s.pnl_pct*100).toFixed(0)}%</span></div>`;
  }
  return h+`</div><p class="foot">Based on what actually happened in Indian markets
    during each of these events.</p></div>`;
}

/* ---------- plumbing ---------- */
async function health(){
  try{const d=await(await fetch(api('/api/health'))).json();
    stEl.textContent=d.distinct_model_families<2?'1 AI model':`${d.models.length} AI models`;
  }catch(e){stEl.textContent='offline';}
}

const EXAMPLES=[
  'Will the Nifty 50 fall below 22,900 in the next 30 days?',
  'What is the repo rate right now?',
  'What happens to a portfolio in a market crash?'
];

function intro(){
  let h=`<div class="intro"><h2>Ask a question about Indian markets.</h2>
    <p>Ten AI advisors — each given a deliberately different outlook — look at live
    data from the RBI and the stock exchange, then tell you how likely something is
    and how much they disagreed.</p>
    <p>You can also just ask for a number, like today's repo rate.</p>
    <div class="chips">`;
  for(const e of EXAMPLES) h+=`<button class="chip" type="button" data-q="${esc(e)}">${esc(e)}</button>`;
  return h+`</div></div>`;
}

async function submit(text){
  if(busy)return; busy=true; go.disabled=true;
  document.querySelector('.intro')?.remove();
  add(esc(text),'you');
  const pending=add('<span class="load">Thinking</span>');
  try{
    const r=await fetch(api('/api/ask/stream'),{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({question:text,rounds:2,horizon_days:30})});
    if(!r.ok) throw new Error('Server error '+r.status);
    const rd=r.body.getReader(),dec=new TextDecoder(); let buf='';
    while(true){
      const{done,value}=await rd.read(); if(done)break;
      buf+=dec.decode(value,{stream:true});
      const parts=buf.split('\n\n'); buf=parts.pop();
      for(const part of parts){
        const ev=(part.match(/^event: (.+)$/m)||[])[1];
        const dl=(part.match(/^data: ([\s\S]+)$/m)||[])[1];
        if(!ev||!dl)continue;
        let d; try{d=JSON.parse(dl)}catch(e){continue}
        if(ev==='status'){
          const nice={'classified':'Working out what you asked',
            'assembling point-in-time evidence':'Fetching live market data',
            'convening council':'Asking the advisors',
            'fetching live data':'Fetching live market data',
            'running stress scenarios':'Checking past crises'}[d.stage]||d.stage;
          pending.innerHTML=`<span class="load">${esc(nice)}</span>`;
        }else if(ev==='error'){
          pending.className='err'; pending.textContent='Something went wrong: '+d.error;
        }else if(ev==='done'){
          pending.remove();
          add(d.route==='council'?renderCouncil(d):d.route==='data'?renderData(d):renderRisk(d));
        }
      }
    }
  }catch(e){ pending.className='err';
    pending.textContent='Could not get an answer: '+e.message; }
  finally{ busy=false; go.disabled=false; qEl.focus(); }
}

log.addEventListener('click',e=>{
  const c=e.target.closest('.chip'); if(c) submit(c.dataset.q);});
form.addEventListener('submit',e=>{e.preventDefault();
  const t=qEl.value.trim(); if(!t)return; qEl.value=''; qEl.style.height='auto'; submit(t);});
qEl.addEventListener('keydown',e=>{
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();form.requestSubmit();}});
qEl.addEventListener('input',()=>{qEl.style.height='auto';
  qEl.style.height=Math.min(qEl.scrollHeight,150)+'px';});

add(intro());
health(); setInterval(health,60000);
</script>
</body>
</html>
"""
