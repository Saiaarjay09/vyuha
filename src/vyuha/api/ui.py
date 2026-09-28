"""The web console.

Editorial rather than chat: a masthead, a standfirst paragraph that answers the
question in prose, then numbered sections underneath for anyone who wants the
detail. Built for a reader who has never used a risk system.

Three rules the design follows:
  - Say the answer in a sentence before saying it as a number.
  - Never show a term without explaining it in the same breath.
  - Never hide the uncertainty to look more confident.
"""

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vyuha</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,500;9..144,700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --paper:#faf7f2; --card:#fffdfa; --ink:#1a1714; --ink2:#4a443c;
  --muted:#7d7469; --faint:#a89f92; --rule:#e2dbd0; --rule2:#efe9e0;
  --accent:#8c2f22; --accent2:#b8442f;
  --no:#2f6b4f; --mid:#a8761d; --yes:#a33a28;
  --display:"Fraunces",Georgia,"Times New Roman",serif;
  --body:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,sans-serif;
  --num:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root{
  --paper:#14120f; --card:#1b1815; --ink:#f0ebe3; --ink2:#c9c0b4;
  --muted:#968c7e; --faint:#6b6358; --rule:#2e2925; --rule2:#252019;
  --accent:#e0705a; --accent2:#c9553f;
  --no:#5aa87d; --mid:#d4a24a; --yes:#e07a63;
}}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--body);
  font-size:16px;line-height:1.65;display:flex;flex-direction:column;
  -webkit-font-smoothing:antialiased}

/* ---------- masthead ---------- */
header{background:var(--card);border-bottom:1px solid var(--rule);
  padding:26px 20px 18px;text-align:center;position:relative}
header::after{content:"";position:absolute;left:0;right:0;bottom:4px;height:1px;
  background:var(--rule);opacity:.55}
.mast{max-width:760px;margin:0 auto}
.mast h1{font-family:var(--display);font-weight:700;font-size:clamp(40px,10vw,74px);
  letter-spacing:.14em;margin:0;line-height:.95;text-indent:.14em;
  font-variation-settings:"opsz" 144}
.mast .sanskrit{font-family:var(--display);font-size:clamp(15px,3.4vw,19px);
  color:var(--accent);letter-spacing:.34em;margin:6px 0 0;text-indent:.34em;font-weight:300}
.mast .rule{display:flex;align-items:center;gap:14px;margin:14px auto 0;max-width:460px}
.mast .rule::before,.mast .rule::after{content:"";flex:1;height:1px;background:var(--rule)}
.mast .rule span{font-size:10.5px;letter-spacing:.24em;text-transform:uppercase;
  color:var(--muted);white-space:nowrap}
.mast .strap{font-family:var(--display);font-style:italic;font-weight:300;
  color:var(--ink2);font-size:14.5px;margin:12px 0 0}
.stat{position:absolute;top:14px;right:18px;font-size:11px;color:var(--faint);
  letter-spacing:.06em}

main{flex:1;overflow-y:auto;padding:30px 20px 10px}
.wrap{max-width:720px;margin:0 auto;display:flex;flex-direction:column;gap:26px}

/* ---------- intro ---------- */
.intro h2{font-family:var(--display);font-weight:500;font-size:27px;line-height:1.25;
  margin:0 0 12px;letter-spacing:-.01em}
.intro p{margin:0 0 12px;color:var(--ink2);font-size:15.5px}
.eg{margin-top:18px;border-top:1px solid var(--rule);padding-top:14px}
.eg .lbl{font-size:10.5px;letter-spacing:.2em;text-transform:uppercase;
  color:var(--muted);margin-bottom:10px}
.chip{display:block;width:100%;text-align:left;background:none;border:0;
  border-bottom:1px solid var(--rule2);padding:11px 2px;cursor:pointer;
  font-family:var(--display);font-size:16.5px;color:var(--ink);line-height:1.4;
  transition:color .12s,padding-left .12s}
.chip:hover{color:var(--accent);padding-left:8px}
.chip::before{content:"→ ";color:var(--faint)}

/* ---------- question ---------- */
.ask{font-family:var(--display);font-size:21px;font-weight:500;line-height:1.35;
  border-left:3px solid var(--accent);padding:2px 0 2px 16px;color:var(--ink)}

/* ---------- article ---------- */
article{background:var(--card);border:1px solid var(--rule);border-radius:3px;
  padding:30px 30px 26px}
.verdict{font-family:var(--display);font-size:clamp(30px,7vw,42px);font-weight:700;
  line-height:1.05;margin:0 0 4px;letter-spacing:-.015em}
.pline{font-size:14px;color:var(--muted);margin:0 0 20px;letter-spacing:.02em}
.gauge{height:3px;background:var(--rule2);margin:0 0 6px;position:relative}
.gauge i{display:block;height:100%;transition:width .6s cubic-bezier(.2,.8,.2,1)}
.gscale{display:flex;justify-content:space-between;font-size:10.5px;
  letter-spacing:.14em;text-transform:uppercase;color:var(--faint);margin-bottom:22px}

/* the standfirst: the whole answer in one paragraph */
.standfirst{font-family:var(--display);font-size:18.5px;line-height:1.62;
  color:var(--ink);margin:0;font-weight:300}
.standfirst b{font-weight:700}
.prelim{font-size:12.5px;color:var(--mid);margin-top:10px;font-style:italic}

.caution{margin-top:20px;padding:13px 16px;border-left:2px solid var(--mid);
  background:var(--rule2);font-size:14px;color:var(--ink2)}
.caution b{color:var(--ink)}

/* ---------- sections ---------- */
.sections{margin-top:32px;padding-top:6px;border-top:2px solid var(--ink);}
.sec{padding:22px 0;border-bottom:1px solid var(--rule2)}
.sec:last-child{border-bottom:none;padding-bottom:4px}
.sec h3{font-family:var(--display);font-size:12px;font-weight:700;margin:0 0 14px;
  letter-spacing:.2em;text-transform:uppercase;color:var(--muted);
  display:flex;align-items:baseline;gap:10px}
.sec h3 .n{font-size:11px;color:var(--faint);font-variant-numeric:tabular-nums}

.adv{display:grid;grid-template-columns:52px 1fr;gap:14px;padding:12px 0;
  border-bottom:1px solid var(--rule2)}
.adv:last-child{border-bottom:none}
.adv .p{font-family:var(--num);font-size:15px;font-weight:600;text-align:right;padding-top:2px}
.adv .nm{font-weight:600;font-size:15px}
.adv .rl{font-size:13px;color:var(--faint);margin:1px 0 4px}
.adv .sy{font-size:14.5px;color:var(--ink2)}

table{width:100%;border-collapse:collapse;font-size:14.5px}
td{padding:7px 0;border-bottom:1px solid var(--rule2);vertical-align:baseline}
td:first-child{color:var(--ink2)}
td:last-child{text-align:right;font-family:var(--num);font-weight:600;white-space:nowrap}
tr:last-child td{border-bottom:none}

blockquote{margin:0;padding:0 0 0 16px;border-left:2px solid var(--rule);
  font-family:var(--display);font-size:16px;font-style:italic;color:var(--ink2);line-height:1.6}
.foot{margin-top:26px;padding-top:14px;border-top:1px solid var(--rule);
  font-size:12.5px;color:var(--faint);line-height:1.6}

.sys{color:var(--ink2);font-size:15px;white-space:pre-wrap}
.err{color:var(--yes);font-size:15px}
.load{font-family:var(--display);font-size:17px;color:var(--muted);font-style:italic}
.bar{height:2px;background:var(--rule2);margin-top:10px;max-width:260px}
.bar i{display:block;height:100%;background:var(--accent);transition:width .3s}

/* ---------- composer ---------- */
footer{position:sticky;bottom:0;background:var(--card);border-top:1px solid var(--rule);
  padding:14px 20px 16px}
form{display:flex;gap:12px;max-width:720px;margin:0 auto;align-items:flex-end}
textarea{flex:1;font-family:var(--body);font-size:16px;padding:12px 14px;
  border:1px solid var(--rule);border-radius:2px;background:var(--paper);color:var(--ink);
  resize:none;min-height:46px;max-height:150px;outline:none;line-height:1.45}
textarea:focus{border-color:var(--accent)}
button.go{background:var(--accent);color:#fff;border:0;border-radius:2px;
  padding:0 22px;height:46px;font-family:var(--display);font-size:15px;font-weight:500;
  letter-spacing:.09em;text-transform:uppercase;cursor:pointer;flex-shrink:0}
button.go:disabled{opacity:.35;cursor:not-allowed}
.tip{max-width:720px;margin:9px auto 0;color:var(--faint);font-size:11.5px;
  text-align:center;letter-spacing:.04em}

@media(max-width:640px){
  main{padding:22px 15px 8px} article{padding:22px 19px 20px}
  header{padding:20px 15px 14px} footer{padding:12px 15px 14px}
  .standfirst{font-size:17px} .adv{grid-template-columns:46px 1fr;gap:11px}
}
</style>
</head>
<body>

<header>
  <span class="stat" id="stat"></span>
  <div class="mast">
    <h1>VYUHA</h1>
    <p class="sanskrit">व्यूह</p>
    <div class="rule"><span>Global Markets · An Indian View</span></div>
    <p class="strap">Ten advisors, deliberately disagreeing, reading today&rsquo;s data</p>
  </div>
</header>

<main><div class="wrap" id="log"></div></main>

<footer>
  <form id="f">
    <textarea id="q" rows="1" placeholder="Ask about any market — Nifty, gold, US stocks, the rupee…"></textarea>
    <button class="go" id="go" type="submit">Ask</button>
  </form>
  <div class="tip">Free and open source · Calibrated uncertainty, not investment advice</div>
</footer>

<script>
const BASE=location.pathname.replace(/\/+$/,''), api=p=>BASE+p;

// Access key. Arrives once as ?key=... in a shared link, then persists so the
// person need not keep the query string. It is stripped from the address bar
// immediately: a key sitting in the URL ends up in history, in screenshots and
// in anything the page later links out to.
let KEY='';
try{
  const u=new URL(location.href);
  const fromUrl=u.searchParams.get('key');
  if(fromUrl){
    localStorage.setItem('vyuha_key',fromUrl);
    u.searchParams.delete('key');
    history.replaceState({},'',u.pathname+u.search+u.hash);
  }
  KEY=localStorage.getItem('vyuha_key')||'';
}catch(e){ /* private mode: fall back to a key-less session */ }

const authHeaders=()=>KEY?{'X-Vyuha-Key':KEY}:{};
const log=document.getElementById('log'), form=document.getElementById('f'),
      qEl=document.getElementById('q'), go=document.getElementById('go'),
      statEl=document.getElementById('stat');
let busy=false;

const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=v=>typeof v==='number'?v.toLocaleString('en-IN',{maximumFractionDigits:2}):esc(v);

const LABELS={
  REPO_RATE:'Repo rate (RBI policy rate)', SDF_RATE:'Standing deposit facility',
  MSF_RATE:'Marginal standing facility', BANK_RATE:'Bank rate',
  REVERSE_REPO_RATE:'Reverse repo rate', CRR:'Cash reserve ratio', SLR:'Statutory liquidity ratio',
  USDINR:'Rupees per US dollar', GBPINR:'Rupees per pound', EURINR:'Rupees per euro',
  JPYINR_100:'Rupees per 100 yen', NIFTY_50:'Nifty 50', NIFTY_BANK:'Bank Nifty',
  INDIA_VIX:'India VIX (fear gauge)', NIFTY_MIDCAP_100:'Nifty Midcap 100',
  DII_NET_CASH:'Indian institutions bought', FII_FPI_NET_CASH:'Foreign investors bought',
  NIFTY_PUT_CALL_RATIO:'Put-call ratio', NIFTY_ATM_IV:'Options-implied volatility',
  US10Y:'US 10-year yield', BRENT:'Brent crude',
  USDINR_SPOT:'Rupees per US dollar', SP500:'S&P 500', NASDAQ:'Nasdaq',
  DOW:'Dow Jones', VIX:'US VIX', DOLLAR_INDEX:'US dollar index',
  US_10Y:'US 10-year yield', US_2Y:'US 2-year yield', FED_FUNDS:'Fed funds rate',
  EURO_10Y:'Euro area 10-year', JAPAN_10Y:'Japan 10-year', UK_10Y:'UK 10-year',
  GOLD_INR:'Gold in rupees', SILVER_INR:'Silver in rupees', BRENT_INR:'Brent in rupees'
};
const nice=k=>LABELS[k]||k.replace(/_/g,' ').toLowerCase().replace(/^./,c=>c.toUpperCase());
// Names that read naturally mid-sentence. The table labels above carry
// parentheticals for clarity; those read badly in prose.
const PROSE={REPO_RATE:'repo rate',NIFTY_50:'Nifty 50',INDIA_VIX:'India VIX',
  USDINR:'rupee',BRENT:'Brent crude',NIFTY_BANK:'Bank Nifty'};
const proseName=k=>PROSE[k]||nice(k).toLowerCase();
// Lowercase only the leading character, so RBI and VIX survive.
const lead=s=>s?s.charAt(0).toLowerCase()+s.slice(1):'';
const ROLES={hawk:'Worries about inflation',dove:'Worries about weak growth',
  value_bear:'Thinks shares are overpriced',momentum_bull:'Follows the trend',
  global_macro:'Watches the dollar and oil',flows:'Watches who is buying and selling',
  quant:'Trusts only the numbers',policy:'Watches the government and RBI',
  behavioural:'Watches the mood of the crowd',red_team:'Argues against everyone else'};

function verdict(p){
  if(p<0.10)return['Very unlikely','var(--no)'];
  if(p<0.30)return['Unlikely','var(--no)'];
  if(p<0.45)return['Probably not','var(--mid)'];
  if(p<0.55)return['Too close to call','var(--mid)'];
  if(p<0.70)return['Fairly likely','var(--mid)'];
  if(p<0.90)return['Likely','var(--yes)'];
  return['Very likely','var(--yes)'];
}
function odds(p){const n=Math.round(1/(p<0.5?p:1-p));
  if(!isFinite(n)||n<2||n>200)return'';
  return p<0.5?`about a 1 in ${n} chance`:`about a ${n-1} in ${n} chance`;}
function agreeWord(d,n){if(n<2)return['',''];
  if(d<0.05)return['agreed almost entirely','though identical advisors agreeing proves less than it seems'];
  if(d<0.12)return['mostly agreed','with a few leaning the other way'];
  if(d<0.22)return['disagreed noticeably','so treat this as a rough guide, not a firm number'];
  return['disagreed sharply','which means there is no reliable answer here — the disagreement is the finding'];}

function add(html,cls){const d=document.createElement('div');
  if(cls)d.className=cls;d.innerHTML=html;log.appendChild(d);
  d.scrollIntoView({block:'nearest',behavior:'smooth'});return d;}

/* ------- the standfirst: whole answer as one paragraph ------- */
function standfirst(d){
  const p=d.probability,[word]=verdict(p),o=odds(p);
  const ok=d.members.filter(m=>m.ok);
  const ps=ok.map(m=>m.probability).filter(x=>x!=null).sort((a,b)=>a-b);
  const [agree,caveat]=agreeWord(d.dispersion,d.n_members);
  let far=null,gap=-1;
  for(const m of ok){const g=Math.abs(m.probability-p);if(g>gap){gap=g;far=m;}}

  let s=`<b>${word}</b> — the council puts this at <b>${(p*100).toFixed(0)}%</b>`;
  s+=o?`, ${o}. `:'. ';
  s+=`Its ${d.n_members} advisors ${agree}`;
  if(ps.length>1) s+=`, with estimates from ${(ps[0]*100).toFixed(0)}% to ${(ps[ps.length-1]*100).toFixed(0)}%`;
  s+=`, ${caveat}. `;
  if(far&&gap>0.1) s+=`The strongest dissent came from <b>${esc(far.name.replace(/_/g,' '))}</b>, `+
    `who ${esc(lead(ROLES[far.name]||''))}, putting it at ${(far.probability*100).toFixed(0)}%. `;
  if(d.evidence?.length){
    const key=d.evidence.filter(e=>['NIFTY_50','INDIA_VIX','REPO_RATE'].includes(e.label))
      .map(e=>`the ${proseName(e.label)} at ${fmt(e.value)}`);
    s+=`They reasoned from ${d.evidence.length} live figures`+
       (key.length?`, including ${key.slice(0,-1).join(', ')}${key.length>1?' and ':''}${key[key.length-1]}`:'')+`. `;
  }
  s+=`This is an estimate of how uncertain things are — not a prediction.`;
  return s;
}

function renderCouncil(d,preliminary){
  const p=d.probability,[word,col]=verdict(p);
  let h=`<article>
    <p class="verdict" style="color:${col}">${word}</p>
    <p class="pline">${(p*100).toFixed(0)}% chance · resolves ${esc(d.resolves||'')}</p>
    <div class="gauge"><i style="width:${Math.max(p*100,1)}%;background:${col}"></i></div>
    <div class="gscale"><span>Won't happen</span><span>Will happen</span></div>
    <p class="standfirst">${standfirst(d)}</p>`;

  if(preliminary) h+=`<p class="prelim">First-round answer — the advisors are now
      reviewing each other's views, so this may shift. Usually not by much.</p>`;
  if(d.independence_warning)
    h+=`<div class="caution"><b>Worth knowing.</b> Every advisor here runs on the same
        AI model, so they tend to make the same mistakes. Their agreement means less
        than it looks.</div>`;

  h+=`<div class="sections">`;
  let n=0;
  const ok=d.members.filter(m=>m.ok);
  if(ok.length){
    h+=`<div class="sec"><h3><span class="n">${String(++n).padStart(2,'0')}</span> The advisors</h3>`;
    for(const m of [...ok].sort((a,b)=>b.probability-a.probability)){
      const [,c]=verdict(m.probability);
      h+=`<div class="adv"><span class="p" style="color:${c}">${(m.probability*100).toFixed(0)}%</span>
          <span><span class="nm">${esc(m.name.replace(/_/g,' '))}</span>
          <div class="rl">${esc(ROLES[m.name]||'')}</div>
          ${m.reasoning?`<div class="sy">${esc(m.reasoning)}</div>`:''}</span></div>`;
    }
    const bad=d.members.length-ok.length;
    if(bad)h+=`<p class="rl" style="margin-top:10px">${bad} advisor${bad>1?'s':''} failed to answer and ${bad>1?'were':'was'} excluded.</p>`;
    h+=`</div>`;
  }
  if(d.counterargument){
    h+=`<div class="sec"><h3><span class="n">${String(++n).padStart(2,'0')}</span> The case against</h3>
        <blockquote>${esc(d.counterargument)}</blockquote></div>`;
  }
  if(d.context?.length){
    h+=`<div class="sec"><h3><span class="n">${String(++n).padStart(2,'0')}</span> Headlines they saw</h3>`;
    for(const c of d.context){
      const age=c.age_hours==null?'undated':`${Math.round(c.age_hours)}h ago`;
      const badge=c.tier==='primary'
        ? '<span style="color:var(--no);font-weight:600">official</span>'
        : '<span style="color:var(--faint)">press</span>';
      h+=`<div class="adv"><span class="p" style="font-size:12px;color:var(--faint)">${esc(c.id)}</span>
          <span><span class="nm" style="font-weight:500">${esc(c.title)}</span>
          <div class="rl">${badge} · ${esc(c.source)} · ${age}${c.flags&&c.flags.length?` · <span style="color:var(--mid)">sanitised: ${esc(c.flags.join(', '))}</span>`:''}</div></span></div>`;
    }
    h+=`<p class="rl" style="margin-top:12px">Recent headlines, filtered from
        ~100 retrieved items. <b>These are untrusted third-party text</b> — a
        report of what someone published, not established fact. Advisors are
        instructed to weigh them well below the figures, and any text trying to
        instruct them is stripped and flagged.</p></div>`;
  }

  if(d.evidence?.length){
    h+=`<div class="sec"><h3><span class="n">${String(++n).padStart(2,'0')}</span> The evidence</h3><table>`;
    for(const e of d.evidence) h+=`<tr><td>${esc(nice(e.label))}</td><td>${fmt(e.value)}</td></tr>`;
    h+=`</table><p class="rl" style="margin-top:12px">Pulled live from the RBI, the NSE
        and public sources. Advisors may use only these figures — inventing numbers is
        detected and flagged.</p></div>`;
  }
  h+=`<div class="sec"><h3><span class="n">${String(++n).padStart(2,'0')}</span> Method</h3><table>
      <tr><td>Combined probability</td><td>${(p*100).toFixed(2)}%</td></tr>
      <tr><td>Spread between advisors</td><td>${d.dispersion?.toFixed(3)??'—'}</td></tr>
      <tr><td>Advisors answering</td><td>${d.n_members}</td></tr></table>
      <p class="rl" style="margin-top:12px;white-space:pre-wrap">${esc((d.notes||[]).join('\n'))}</p></div>`;
  h+=`</div><p class="foot">Vyuha estimates uncertainty; it does not predict markets.
      Do not make financial decisions from it.</p></article>`;
  return h;
}

function renderData(d){
  let h=`<article><p class="verdict" style="font-size:30px">Live figures</p>
    <p class="standfirst">Read straight from the source — no AI involved and nothing
    estimated. These are the current published values.</p>
    <div class="sections"><div class="sec"><h3><span class="n">01</span> Current values</h3><table>`;
  for(const m of d.matches.slice(0,16))
    h+=`<tr><td>${esc(nice(m.label))}</td><td>${fmt(m.value)}${m.unit==='pct'?'%':m.unit==='INR'?'':m.unit?' '+esc(m.unit):''}</td></tr>`;
  return h+`</table></div></div><p class="foot">Source: RBI and NSE, fetched just now.</p></article>`;
}

function renderRisk(d){
  let h=`<article><p class="verdict" style="font-size:30px">If history repeated</p>
    <p class="standfirst">What an example portfolio would have lost in each of these real
    Indian market crises. This uses a sample portfolio, not yours.</p>
    <div class="sections"><div class="sec"><h3><span class="n">01</span> Losses by scenario</h3><table>`;
  for(const s of d.scenarios.slice(0,8)){
    const c=s.pnl_pct<-0.3?'var(--yes)':s.pnl_pct<-0.1?'var(--mid)':'var(--ink)';
    h+=`<tr><td>${esc(s.name)}</td><td style="color:${c}">${(s.pnl_pct*100).toFixed(0)}%</td></tr>`;
  }
  return h+`</table></div></div><p class="foot">Based on what actually happened during each event.</p></article>`;
}

const rs=v=>v==null?'—':'₹'+Math.round(v).toLocaleString('en-IN');

function renderProjection(d){
  const p=d.percentiles, rp=d.real_percentiles, tp=d.post_tax_percentiles,
        np_=d.net_real_percentiles||{};
  const inv=d.total_invested, med=p.p50;
  const mult=med/inv;
  const modeTxt=d.mode==='sip'
    ? `₹${Math.round(d.amount).toLocaleString('en-IN')} every month for ${d.years} years (₹${Math.round(inv).toLocaleString('en-IN')} invested in total)`
    : `₹${Math.round(d.amount).toLocaleString('en-IN')} invested once for ${d.years} years`;

  let h=`<article>
    <p class="verdict" style="font-size:34px">${rs(med)}</p>
    <p class="pline">most likely outcome · ${esc(d.asset_label)}</p>
    <div class="gauge"><i style="width:${Math.min(100,(mult/3)*100).toFixed(0)}%;background:var(--accent)"></i></div>
    <div class="gscale"><span>${rs(p.p5)} (unlucky)</span><span>${rs(p.p95)} (lucky)</span></div>

    <p class="standfirst">${esc(modeTxt)} lands most often around <b>${rs(med)}</b>,
    but the honest range is wide: <b>${rs(p.p5)}</b> to <b>${rs(p.p95)}</b>.
    That headline figure shrinks twice before it reaches you: tax takes it to
    <b>${rs(tp.p50)}</b>, and ${(d.inflation_assumed*100).toFixed(1)}% inflation
    leaves it worth <b>${rs(np_.p50)}</b> in today's money — against the
    <b>${rs(inv)}</b> you put in. There is a <b>${(d.prob_loss*100).toFixed(0)}% chance
    you end up with less than you put in</b>, and a
    <b>${(d.prob_below_inflation*100).toFixed(0)}% chance</b> you end up no better
    off than if prices had simply risen. Along the way, a fall of about
    <b>${Math.abs(d.max_drawdown_median*100).toFixed(0)}%</b> at some point is typical.</p>`;

  h+=`<div class="caution"><b>This is not a prediction, and not advice.</b>
      It resamples ${esc(d.sample)} of actual history, which assumes the next
      ${d.years} years resemble some stretch of the past. They may not.</div>`;

  h+=`<div class="sections">`;
  h+=`<div class="sec"><h3><span class="n">01</span> The range of outcomes</h3><table>
    <tr><td>Very unlucky (5th percentile)</td><td>${rs(p.p5)}</td></tr>
    <tr><td>Unlucky (25th)</td><td>${rs(p.p25)}</td></tr>
    <tr><td><b>Middle (50th)</b></td><td><b>${rs(p.p50)}</b></td></tr>
    <tr><td>Lucky (75th)</td><td>${rs(p.p75)}</td></tr>
    <tr><td>Very lucky (95th)</td><td>${rs(p.p95)}</td></tr>
    <tr><td>You put in</td><td>${rs(inv)}</td></tr></table></div>`;

  h+=`<div class="sec"><h3><span class="n">02</span> What it's really worth</h3><table>
    <tr><td>You put in</td><td>${rs(inv)}</td></tr>
    <tr><td>Middle outcome, before anything</td><td>${rs(p.p50)}</td></tr>
    <tr><td>…less tax</td><td>${rs(tp.p50)}</td></tr>
    <tr><td><b>…less inflation — worth today</b></td><td><b>${rs(np_.p50)}</b></td></tr>
    <tr><td>Typical yearly growth, before tax and inflation</td><td>${(d.median_cagr*100).toFixed(1)}%</td></tr>
    </table><p class="rl" style="margin-top:12px">${esc(d.tax_note)}
    Inflation assumed ${(d.inflation_assumed*100).toFixed(1)}% a year.</p></div>`;

  h+=`<div class="sec"><h3><span class="n">03</span> The risks</h3><table>
    <tr><td>Chance of ending below what you put in</td><td>${(d.prob_loss*100).toFixed(0)}%</td></tr>
    <tr><td>Chance of not beating inflation</td><td>${(d.prob_below_inflation*100).toFixed(0)}%</td></tr>
    <tr><td>Chance a fixed deposit would have done better</td><td>${(d.prob_below_fd*100).toFixed(0)}%</td></tr>
    <tr><td>Typical worst fall along the way</td><td>${(d.max_drawdown_median*100).toFixed(0)}%</td></tr>
    </table></div>`;

  if(d.comparison?.length){
    h+=`<div class="sec"><h3><span class="n">04</span> Same money elsewhere</h3><table>`;
    for(const c of d.comparison){
      if(c.median==null) continue;
      h+=`<tr><td>${esc(c.asset)}</td><td>${rs(c.median)} <span style="color:var(--faint);font-weight:400">· ${(c.prob_loss*100).toFixed(0)}% loss risk</span></td></tr>`;
    }
    h+=`</table><p class="rl" style="margin-top:12px">Median outcome for the same
        amount and horizon. Higher medians come with wider ranges — that is the
        trade, not a free lunch.</p></div>`;
  }

  h+=`</div><p class="foot">${(d.caveats||[]).map(esc).join('<br>')}</p></article>`;
  return h;
}

function renderGoal(d){
  const gap=d.monthly_for_80pct/d.monthly_required;
  return `<article>
    <p class="verdict" style="font-size:34px">${rs(d.monthly_required)}<span style="font-size:18px;color:var(--muted);font-weight:400"> / month</span></p>
    <p class="pline">for a roughly even chance · ${esc(d.asset_label)}</p>
    <p class="standfirst">To reach <b>${rs(d.target)}</b> in ${d.years} years,
    saving <b>${rs(d.monthly_required)}</b> a month gets you there in about half
    of simulated histories. For a <b>four-in-five</b> chance you would need
    <b>${rs(d.monthly_for_80pct)}</b> — ${((gap-1)*100).toFixed(0)}% more. That
    difference is what certainty costs, and most calculators never show it.
    A lump sum today of <b>${rs(d.lumpsum_required)}</b> would do the same job.</p>
    <div class="caution"><b>${rs(d.target)} then is not ${rs(d.target)} now.</b>
      At ${(d.inflation_assumed*100).toFixed(1)}% inflation it will buy what about
      <b>${rs(d.target_in_todays_money)}</b> buys today. If your goal is defined in
      today's money, aim higher.</div>
    <div class="sections"><div class="sec"><h3><span class="n">01</span> The plan</h3><table>
      <tr><td>Monthly, ~50% chance</td><td>${rs(d.monthly_required)}</td></tr>
      <tr><td><b>Monthly, ~80% chance</b></td><td><b>${rs(d.monthly_for_80pct)}</b></td></tr>
      <tr><td>Or a lump sum today</td><td>${rs(d.lumpsum_required)}</td></tr>
      <tr><td>Total you would contribute</td><td>${rs(d.total_contributed)}</td></tr>
      <tr><td>Target, in today's money</td><td>${rs(d.target_in_todays_money)}</td></tr>
    </table></div></div>
    <p class="foot">${(d.caveats||[]).map(esc).join('<br>')}</p></article>`;
}

function renderPortfolio(d){
  const bad=d.stress[0];
  const slow=d.liquidity.filter(l=>l.days>1);
  let h=`<article>
    <p class="verdict" style="font-size:32px">${rs(d.total)}</p>
    <p class="pline">across ${d.holdings.length} holdings · effective spread ${d.concentration.effective_n?.toFixed(1)} ways</p>
    <p class="standfirst">Your biggest single holding is
    <b>${(d.concentration.top1_pct*100).toFixed(0)}%</b> of the total, and the top
    five are <b>${(d.concentration.top5_pct*100).toFixed(0)}%</b>. Typical yearly
    swing is around <b>±${(d.annual_vol*100).toFixed(0)}%</b>, so a normal year
    could plausibly land anywhere between <b>${rs(d.one_year_range[0])}</b> and
    <b>${rs(d.one_year_range[1])}</b>. The worst scenario in Indian market history
    — ${esc(bad.name)} — would have cost you
    <b>${(bad.loss_pct*100).toFixed(0)}%</b>, about ${rs(Math.abs(bad.loss))}.</p>`;

  h+=`<div class="sections">`;
  h+=`<div class="sec"><h3><span class="n">01</span> What you hold</h3><table>`;
  for(const x of d.holdings)
    h+=`<tr><td>${esc(x.name)} <span style="color:var(--faint)">· ${esc(x.label)}${x.guessed?' (assumed)':''}</span></td><td>${rs(x.value)}</td></tr>`;
  h+=`</table></div>`;

  h+=`<div class="sec"><h3><span class="n">02</span> If history repeated</h3><table>`;
  for(const s2 of d.stress.slice(0,6)){
    const c=s2.loss_pct<-0.3?'var(--yes)':s2.loss_pct<-0.1?'var(--mid)':'var(--ink)';
    h+=`<tr><td>${esc(s2.name)} <span style="color:var(--faint)">${esc(s2.period)}</span></td>
        <td style="color:${c}">${(s2.loss_pct*100).toFixed(0)}% · ${rs(Math.abs(s2.loss))}</td></tr>`;
  }
  h+=`</table><p class="rl" style="margin-top:12px">${esc(d.stress[0].lesson)}</p></div>`;

  if(slow.length){
    h+=`<div class="sec"><h3><span class="n">03</span> How fast you could get out</h3><table>`;
    for(const l of slow.slice(0,6))
      h+=`<tr><td>${esc(l.name)}</td><td>${l.days.toFixed(1)} days</td></tr>`;
    h+=`</table><p class="rl" style="margin-top:12px">At 15% of typical daily
        volume. In a crash volume dries up and these get longer.</p></div>`;
  }
  return h+`</div><p class="foot">${(d.caveats||[]).map(esc).join('<br>')}</p></article>`;
}

function renderFund(d){
  if(!d.matches.length)
    return `<article><p class="verdict" style="font-size:28px">No match</p>
      <p class="standfirst">${esc((d.caveats||[])[0]||'Nothing found.')}</p></article>`;
  const top=d.matches[0];
  let h=`<article>
    <p class="verdict" style="font-size:32px">₹${top.nav.toFixed(2)}</p>
    <p class="pline">${esc(top.name)} · ${esc(top.plan)} ${esc(top.option)}</p>
    <p class="standfirst">Run by <b>${esc(top.amc)}</b>, NAV as of ${esc(top.date)}.
    There are <b>${d.category_peers}</b> other schemes in the same category, out of
    <b>${d.total_schemes.toLocaleString('en-IN')}</b> in India.</p>
    <div class="sections"><div class="sec"><h3><span class="n">01</span> Matching schemes</h3><table>`;
  for(const m of d.matches)
    h+=`<tr><td>${esc(m.plan)} · ${esc(m.option)}</td><td>₹${m.nav.toFixed(2)}</td></tr>`;
  h+=`</table></div></div>`;
  return h+`<p class="foot">${(d.caveats||[]).map(esc).join('<br>')}</p></article>`;
}

function renderNoModel(d){
  return `<article><p class="verdict" style="font-size:30px;color:var(--mid)">No advisors available</p>
    <p class="standfirst">${esc(d.message)}</p>
    <div class="sections"><div class="sec"><h3><span class="n">01</span> How to enable them</h3>`+
    (d.how_to_fix||[]).map(x=>`<p class="sub">${esc(x)}</p>`).join('')+
    `</div></div><p class="foot">Live figures and stress tests work without a model.</p></article>`;
}

function renderNoData(d){
  return `<article><p class="verdict" style="font-size:30px;color:var(--mid)">Not enough data</p>
    <p class="standfirst">${esc(d.message)}</p>
    <div class="sections"><div class="sec"><h3><span class="n">01</span> What would be needed</h3><table>`+
    (d.catalogued||[]).map(c=>`<tr><td>${esc(c.name)}</td><td>${esc(c.status)}</td></tr>`).join('')+
    `</table></div></div><p class="foot">Guessing would be easy and wrong. This system is
    built to say when it does not know.</p></article>`;
}

async function health(){
  try{const d=await(await fetch(api('/api/health'),{headers:authHeaders()})).json();
    if(d.requires_key && !KEY) statEl.title='This instance needs an access key.';
    statEl.textContent = !d.council_available ? 'data only'
      : d.distinct_model_families<2 ? '1 model'
      : `${d.models.length} models`;
  }catch(e){
    statEl.textContent='offline';
    statEl.title='The page could not reach its own API. Usually an ad/privacy '
      +'blocker, or the server is not running.';
  }
}

const EXAMPLES=['I have ₹8 lakh in HDFC Bank, ₹5 lakh in Reliance and ₹3 lakh in gold',
  'I want ₹1 crore in 15 years',
  'If I invest ₹5 lakh in equity for 7 years, what might I get?',
  'What is the NAV of Parag Parikh Flexi Cap fund?',
  'Will the Nifty 50 fall below 22,900 in the next 30 days?'];

function intro(){
  return `<div class="intro">
    <h2>Ask about markets, anywhere in the world.</h2>
    <p>Ten AI advisors — each deliberately given a different outlook, from inflation
    hawk to trend-follower to one whose only job is to argue against the rest — read
    live data and tell you how likely something is, and how much they disagreed.</p>
    <p>Indian markets in depth: the RBI, the NSE, options, flows. Plus gold, silver,
    crude and metals; the S&amp;P, Nasdaq and world interest rates; 166 currencies;
    and economic data for 217 countries.</p>
    <p><b>Prices are shown in rupees as well as dollars</b> — because a foreign
    asset's return to an Indian investor is the asset's move <i>and</i> the rupee's,
    and the currency is often a third of it.</p>
    <div class="eg"><div class="lbl">Try one</div>`+
    EXAMPLES.map(e=>`<button class="chip" type="button" data-q="${esc(e)}">${esc(e)}</button>`).join('')+
    `</div></div>`;
}

async function submit(text){
  if(busy)return;busy=true;go.disabled=true;
  document.querySelector('.intro')?.remove();
  add(esc(text),'ask');
  const pending=add('<span class="load">Reading the market</span><div class="bar"><i style="width:4%"></i></div>');
  const bar=()=>pending.querySelector('.bar i');
  let prelim=null;
  try{
    const r=await fetch(api('/api/ask/stream'),{method:'POST',
      headers:{'Content-Type':'application/json',...authHeaders()},
      body:JSON.stringify({question:text,rounds:2,horizon_days:30})});
    if(r.status===401){ throw new Error('__NOKEY__'); }
    if(r.status===429){ throw new Error('__RATE__'); }
    if(!r.ok)throw new Error('Server error '+r.status);
    const rd=r.body.getReader(),dec=new TextDecoder();let buf='';
    while(true){
      const{done,value}=await rd.read();if(done)break;
      buf+=dec.decode(value,{stream:true});
      const parts=buf.split('\n\n');buf=parts.pop();
      for(const part of parts){
        const ev=(part.match(/^event: (.+)$/m)||[])[1];
        const dl=(part.match(/^data: ([\s\S]+)$/m)||[])[1];
        if(!ev||!dl)continue;
        let d;try{d=JSON.parse(dl)}catch(e){continue}
        if(ev==='status'){
          const t={'classified':'Understanding the question',
            'assembling point-in-time evidence':'Gathering live market data',
            'convening council':'Consulting the advisors',
            'fetching live data':'Gathering live market data',
            'checking data coverage':'Checking what data exists',
            'simulating outcomes':'Simulating 20,000 possible futures',
            'analysing holdings':'Running your holdings through the risk engine',
            'searching schemes':'Searching 14,000 mutual fund schemes',
            'running stress scenarios':'Replaying past crises'}[d.stage]||d.stage;
          if(!prelim)pending.querySelector('.load').textContent=t;
        }else if(ev==='member'){
          if(!prelim&&bar())bar().style.width=Math.round(6+d.done/d.total*88)+'%';
          if(!prelim)pending.querySelector('.load').textContent=
            `Consulting the advisors — ${d.done} of ${d.total}`;
        }else if(ev==='preliminary'){
          // Show the round-1 answer now rather than holding a spinner for the
          // deliberation round. It is replaced in place when the final
          // verdict arrives.
          if(d && d.probability!=null){
            if(prelim){ prelim.outerHTML=renderCouncil(d,true); prelim=document.querySelector('#prov'); }
            else { pending.style.display='none';
                   prelim=add(renderCouncil(d,true)); prelim.id='prov'; }
          }
        }else if(ev==='error'){
          pending.className='err';pending.textContent='Something went wrong: '+d.error;
        }else if(ev==='done'){
          pending.remove();
          if(prelim){ prelim.remove(); prelim=null; }
          add(d.route==='council'?renderCouncil(d)
             :d.route==='data'?renderData(d)
             :d.route==='no_data'?renderNoData(d)
             :d.route==='no_model'?renderNoModel(d)
             :d.route==='projection'?renderProjection(d)
             :d.route==='goal'?renderGoal(d)
             :d.route==='portfolio'?renderPortfolio(d)
             :d.route==='fund'?renderFund(d)
             :d.route==='projection_unparsed'?renderNoData({message:d.message,catalogued:[]})
             :renderRisk(d));
        }
      }
    }
  }catch(e){
    if(e.message==='__NOKEY__'){
      pending.className='err';
      pending.innerHTML=`<b>This instance needs an access key.</b><br><br>
        It runs on a personal machine, so questions are limited to people with
        the link's key. Open the URL you were given including its
        <code>?key=…</code> part, and it will be remembered on this device.`;
      return;
    }
    if(e.message==='__RATE__'){
      pending.className='err';
      pending.innerHTML=`<b>Too many questions for now.</b><br><br>
        Each one runs a language model on a personal machine, so there is an
        hourly cap. Try again shortly.`;
      return;
    }
    // fetch() reports a blocked request and an unreachable server identically
    // as "Failed to fetch", so the message has to cover both rather than
    // guessing. A content blocker is by far the commonest cause when the page
    // itself loaded but its requests do not.
    const blocked = /failed to fetch|networkerror|load failed/i.test(e.message||'');
    pending.className='err';
    pending.innerHTML = blocked
      ? `<b>Could not reach the server.</b><br><br>
         The page loaded, but its requests were refused before leaving your
         browser. Two usual causes:<br><br>
         1. <b>An ad or privacy blocker</b> (uBlock, AdGuard, Brave Shields,
         Safari content blockers). Pause it for this site and reload &mdash;
         this is the most common cause by far.<br>
         2. <b>The server is asleep.</b> It runs on a personal machine; if that
         machine is off, nothing will load.<br><br>
         <a href="${esc(BASE)}/api/health" target="_blank">Open the health
         check directly</a> &mdash; if that page shows JSON, the server is fine
         and something in the browser is blocking it.`
      : 'Could not get an answer: '+esc(e.message);
  }
  finally{busy=false;go.disabled=false;qEl.focus();}
}

log.addEventListener('click',e=>{const c=e.target.closest('.chip');if(c)submit(c.dataset.q);});
form.addEventListener('submit',e=>{e.preventDefault();
  const t=qEl.value.trim();if(!t)return;qEl.value='';qEl.style.height='auto';submit(t);});
qEl.addEventListener('keydown',e=>{
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();form.requestSubmit();}});
qEl.addEventListener('input',()=>{qEl.style.height='auto';
  qEl.style.height=Math.min(qEl.scrollHeight,150)+'px';});

add(intro());health();setInterval(health,60000);
</script>
</body>
</html>
"""
