"""The static Vyuha site: everything that works without a server.

GitHub Pages is free, always on, and cannot run Python. Most of what people
use Vyuha for turns out not to need Python at all -- the projection is a
bootstrap over 8 KB of historical returns, and portfolio risk is bucketing
plus arithmetic. Both run in a browser.

The one thing that genuinely needs a server is the council, because that needs
a language model at request time. The static site shows the latest recorded
verdicts and says plainly that it cannot answer new questions.
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
  --accent:#8c2f22; --no:#2f6b4f; --mid:#a8761d; --yes:#a33a28;
  --display:"Fraunces",Georgia,serif; --body:"Inter",-apple-system,sans-serif;
  --num:ui-monospace,SFMono-Regular,Menlo,monospace;
}
@media (prefers-color-scheme:dark){:root{
  --paper:#14120f; --card:#1b1815; --ink:#f0ebe3; --ink2:#c9c0b4;
  --muted:#968c7e; --faint:#6b6358; --rule:#2e2925; --rule2:#252019;
  --accent:#e0705a; --no:#5aa87d; --mid:#d4a24a; --yes:#e07a63;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--body);
  font-size:16px;line-height:1.65;-webkit-font-smoothing:antialiased}
header{background:var(--card);border-bottom:1px solid var(--rule);
  padding:26px 20px 18px;text-align:center}
.mast{max-width:760px;margin:0 auto}
.mast h1{font-family:var(--display);font-weight:700;font-size:clamp(38px,9vw,66px);
  letter-spacing:.14em;margin:0;line-height:.95;text-indent:.14em}
.mast .sans{font-family:var(--display);font-size:clamp(14px,3vw,18px);
  color:var(--accent);letter-spacing:.34em;margin:6px 0 0;text-indent:.34em;font-weight:300}
.mast .rule{display:flex;align-items:center;gap:14px;margin:14px auto 0;max-width:470px}
.mast .rule::before,.mast .rule::after{content:"";flex:1;height:1px;background:var(--rule)}
.mast .rule span{font-size:10.5px;letter-spacing:.22em;text-transform:uppercase;
  color:var(--muted);white-space:nowrap}
.mast .strap{font-family:var(--display);font-style:italic;font-weight:300;
  color:var(--ink2);font-size:14px;margin:12px 0 0}

nav{position:sticky;top:0;z-index:5;background:var(--card);
  border-bottom:1px solid var(--rule);padding:0 20px;overflow-x:auto}
nav div{max-width:760px;margin:0 auto;display:flex;gap:4px}
nav button{background:none;border:0;border-bottom:2px solid transparent;
  padding:13px 14px;font-family:var(--body);font-size:14px;color:var(--muted);
  cursor:pointer;white-space:nowrap}
nav button.on{color:var(--ink);border-bottom-color:var(--accent);font-weight:600}

main{max-width:760px;margin:0 auto;padding:26px 20px 60px}
section{display:none} section.on{display:block}
h2{font-family:var(--display);font-weight:500;font-size:25px;margin:0 0 6px}
.lede{color:var(--ink2);font-size:15.5px;margin:0 0 20px}

.card{background:var(--card);border:1px solid var(--rule);border-radius:3px;
  padding:22px;margin-bottom:18px}
label{display:block;font-size:12px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--muted);margin-bottom:6px}
input,select,textarea{width:100%;font-family:var(--body);font-size:16px;
  padding:10px 12px;border:1px solid var(--rule);border-radius:2px;
  background:var(--paper);color:var(--ink);outline:none;margin-bottom:14px}
input:focus,select:focus,textarea:focus{border-color:var(--accent)}
textarea{min-height:84px;resize:vertical}
.row{display:flex;gap:14px}.row>div{flex:1}
button.go{background:var(--accent);color:#fff;border:0;border-radius:2px;
  padding:11px 24px;font-family:var(--display);font-size:15px;font-weight:500;
  letter-spacing:.08em;text-transform:uppercase;cursor:pointer}
button.go:disabled{opacity:.5}

.big{font-family:var(--display);font-size:clamp(28px,7vw,40px);font-weight:700;
  line-height:1.05;margin:0 0 4px;letter-spacing:-.015em}
.sub{color:var(--muted);font-size:13.5px;margin:0 0 16px}
.stand{font-family:var(--display);font-size:17.5px;line-height:1.6;font-weight:300;margin:0}
.stand b{font-weight:700}
table{width:100%;border-collapse:collapse;font-size:14.5px;margin-top:14px}
td{padding:7px 0;border-bottom:1px solid var(--rule2)}
td:last-child{text-align:right;font-family:var(--num);font-weight:600;white-space:nowrap}
tr:last-child td{border-bottom:none}
.caution{margin-top:16px;padding:12px 15px;border-left:2px solid var(--mid);
  background:var(--rule2);font-size:14px;color:var(--ink2)}
.foot{margin-top:18px;padding-top:12px;border-top:1px solid var(--rule);
  font-size:12.5px;color:var(--faint);line-height:1.6}
.h3{font-family:var(--display);font-size:12px;font-weight:700;margin:22px 0 10px;
  letter-spacing:.2em;text-transform:uppercase;color:var(--muted)}
.gauge{height:3px;background:var(--rule2);margin:12px 0 6px}
.gauge i{display:block;height:100%}
.gs{display:flex;justify-content:space-between;font-size:10.5px;
  letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
.pill{display:inline-block;font-size:11px;padding:2px 8px;border-radius:99px;
  background:var(--rule2);color:var(--muted);margin-left:6px}
@media(max-width:620px){.row{flex-direction:column;gap:0}main{padding:20px 15px 50px}}
</style>
</head>
<body>

<header><div class="mast">
  <h1>VYUHA</h1>
  <p class="sans">व्यूह</p>
  <div class="rule"><span>Indian Markets · Open Source</span></div>
  <p class="strap">Calculators that run in your browser, data refreshed daily</p>
</div></header>

<nav><div>
  <button class="on" data-s="plan">Plan a goal</button>
  <button data-s="project">Project an investment</button>
  <button data-s="portfolio">Your portfolio</button>
  <button data-s="market">Today's figures</button>
  <button data-s="council">Council</button>
  <button data-s="about">About</button>
</div></nav>

<main>
<section id="plan" class="on">
  <h2>What will it take to get there?</h2>
  <p class="lede">Most calculators quote the median outcome and call it a plan.
  That has roughly an even chance of working. This shows both numbers.</p>
  <div class="card">
    <div class="row">
      <div><label>Target amount (₹)</label><input id="g_target" value="10000000"></div>
      <div><label>Years</label><input id="g_years" value="15"></div>
    </div>
    <label>Invested in</label>
    <select id="g_asset"></select>
    <button class="go" onclick="doGoal()">Work it out</button>
  </div>
  <div id="g_out"></div>
</section>

<section id="project">
  <h2>What might this become?</h2>
  <p class="lede">A range, never a single number — including the chance of
  ending up with less than you put in.</p>
  <div class="card">
    <div class="row">
      <div><label>Amount (₹)</label><input id="p_amount" value="500000"></div>
      <div><label>Years</label><input id="p_years" value="7"></div>
    </div>
    <div class="row">
      <div><label>Invested in</label><select id="p_asset"></select></div>
      <div><label>How</label><select id="p_mode">
        <option value="lumpsum">One lump sum</option>
        <option value="sip">Monthly (SIP)</option>
      </select></div>
    </div>
    <button class="go" onclick="doProject()">Simulate</button>
  </div>
  <div id="p_out"></div>
</section>

<section id="portfolio">
  <h2>How risky is what you hold?</h2>
  <p class="lede">Describe your holdings in plain English. Nothing is sent
  anywhere — the arithmetic happens on your device.</p>
  <div class="card">
    <label>Your holdings</label>
    <textarea id="pf_text">8 lakh in HDFC Bank, 5 lakh in Reliance, 4 lakh in a midcap fund, 3 lakh in gold and 2 lakh in FD</textarea>
    <button class="go" onclick="doPortfolio()">Analyse</button>
  </div>
  <div id="pf_out"></div>
</section>

<section id="market">
  <h2>Today's figures</h2>
  <p class="lede" id="m_as_of">Loading…</p>
  <div class="card"><div id="m_out"></div></div>
</section>

<section id="council">
  <h2>What the council last said</h2>
  <p class="lede">The council needs a language model running at the moment you
  ask, which a static site cannot do. These are its most recent recorded
  verdicts.</p>
  <div class="card"><div id="c_out">Loading…</div></div>
  <div class="card"><div class="h3">Where it stands</div><div id="s_out"></div></div>
</section>

<section id="about">
  <h2>About</h2>
  <div class="card">
    <p class="stand">Vyuha is an open risk engine for Indian markets. This page
    is the part that works without a server: the simulations run in your
    browser, over real historical returns, and the market figures are refreshed
    by a scheduled job every weekday.</p>
    <div class="h3">What this page cannot do</div>
    <p class="sub">Answer new questions. The council is ten AI advisors with
    deliberately opposed views, and that needs a model running when you ask.
    It shows the latest recorded verdicts instead.</p>
    <div class="h3">Honest limits</div>
    <div id="a_cov"></div>
    <p class="foot">Not investment advice. Simulations resample history, which
    assumes the future resembles some stretch of the past — it may not.
    Source: <a href="https://github.com/Saiaarjay09/vyuha">github.com/Saiaarjay09/vyuha</a>,
    Apache 2.0.</p>
  </div>
</section>
</main>

<script>
const D={};
const rs=v=>v==null||!isFinite(v)?'—':'₹'+Math.round(v).toLocaleString('en-IN');
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('on',x===b));
  document.querySelectorAll('section').forEach(s=>s.classList.toggle('on',s.id===b.dataset.s));
});

/* ---------- the simulation, running here rather than on a server ---------- */
function blockBootstrap(returns,nMonths,nSims,block){
  block=block||12;
  const n=returns.length, nb=Math.ceil(nMonths/block);
  const out=new Float64Array(nSims*nMonths);
  for(let s=0;s<nSims;s++){
    let k=0;
    for(let b=0;b<nb && k<nMonths;b++){
      const start=Math.floor(Math.random()*(n-block+1));
      for(let j=0;j<block && k<nMonths;j++,k++) out[s*nMonths+k]=returns[start+j];
    }
  }
  return out;
}
function pct(arr,q){const a=Float64Array.from(arr).sort();
  const i=(a.length-1)*q/100; const lo=Math.floor(i),hi=Math.ceil(i);
  return a[lo]+(a[hi]-a[lo])*(i-lo);}

function assetReturns(key,nMonths,nSims){
  const a=D.returns.assets[key];
  if(a) return {paths:blockBootstrap(a.returns,nMonths,nSims,12),label:a.label,note:a.note};
  const f=D.returns.fixed[key];
  const mu=Math.pow(1+f.rate,1/12)-1, sd=f.vol/Math.sqrt(12);
  const out=new Float64Array(nSims*nMonths);
  for(let i=0;i<out.length;i++){
    // Box-Muller, so a "fixed" asset still carries its stated volatility.
    const u=Math.random()||1e-9, v=Math.random();
    out[i]=mu+sd*Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v);
  }
  return {paths:out,label:f.label,note:f.note};
}

function simulate(amount,years,key,mode,nSims){
  nSims=nSims||4000;
  const nM=Math.max(1,Math.round(years*12));
  const {paths,label,note}=assetReturns(key,nM,nSims);
  const term=new Float64Array(nSims), dd=new Float64Array(nSims);
  for(let s=0;s<nSims;s++){
    let cum=1,peak=1,worst=0,sip=0;
    const base=s*nM;
    for(let m=0;m<nM;m++){
      cum*=(1+paths[base+m]);
      if(cum>peak)peak=cum;
      const d=cum/peak-1; if(d<worst)worst=d;
      if(mode==='sip') sip+=1/cum;
    }
    term[s]= mode==='sip' ? amount*sip*cum : amount*cum;
    dd[s]=worst;
  }
  const invested = mode==='sip' ? amount*nM : amount;
  return {term,dd,invested,label,note,nM};
}

const INFL=0.055;
function doProject(){
  const amount=+document.getElementById('p_amount').value;
  const years=+document.getElementById('p_years').value;
  const key=document.getElementById('p_asset').value;
  const mode=document.getElementById('p_mode').value;
  if(!(amount>0)||!(years>0)) return;
  const r=simulate(amount,years,key,mode);
  const p=q=>pct(r.term,q);
  const med=p(50), loss=[...r.term].filter(x=>x<r.invested).length/r.term.length;
  const real=med/Math.pow(1+INFL,years);
  const tax=key==='fixed_deposit'||key==='debt_fund'?0.30:0.125;
  const net=med-Math.max(med-r.invested,0)*tax;
  const mdd=pct(r.dd,50);
  document.getElementById('p_out').innerHTML=`<div class="card">
    <p class="big">${rs(med)}</p><p class="sub">most likely outcome · ${esc(r.label)}</p>
    <div class="gauge"><i style="width:${Math.min(100,med/r.invested/3*100)}%;background:var(--accent)"></i></div>
    <div class="gs"><span>${rs(p(5))} unlucky</span><span>${rs(p(95))} lucky</span></div>
    <p class="stand" style="margin-top:16px">${rs(r.invested)} ${mode==='sip'?'contributed over':'invested for'}
      ${years} years lands most often near <b>${rs(med)}</b>, with an honest range
      of <b>${rs(p(5))}</b> to <b>${rs(p(95))}</b>. After tax that is about
      <b>${rs(net)}</b>, and after ${(INFL*100).toFixed(1)}% inflation it is worth
      <b>${rs(net/Math.pow(1+INFL,years))}</b> in today's money. There is a
      <b>${(loss*100).toFixed(0)}% chance</b> of ending below what you put in, and a
      fall of about <b>${Math.abs(mdd*100).toFixed(0)}%</b> along the way is typical.</p>
    <table>
      <tr><td>Very unlucky (5th percentile)</td><td>${rs(p(5))}</td></tr>
      <tr><td>Unlucky (25th)</td><td>${rs(p(25))}</td></tr>
      <tr><td><b>Middle (50th)</b></td><td><b>${rs(med)}</b></td></tr>
      <tr><td>Lucky (75th)</td><td>${rs(p(75))}</td></tr>
      <tr><td>Very lucky (95th)</td><td>${rs(p(95))}</td></tr>
      <tr><td>You put in</td><td>${rs(r.invested)}</td></tr>
    </table>
    <div class="caution">Not a prediction. This resamples real history and assumes
      the next ${years} years resemble some stretch of the past.</div>
    <p class="foot">${esc(r.note)}</p></div>`;
}

function doGoal(){
  const target=+document.getElementById('g_target').value;
  const years=+document.getElementById('g_years').value;
  const key=document.getElementById('g_asset').value;
  if(!(target>0)||!(years>0)) return;
  const nM=Math.max(1,Math.round(years*12)), nSims=4000;
  const {paths,label,note}=assetReturns(key,nM,nSims);
  const perRupee=new Float64Array(nSims), lump=new Float64Array(nSims);
  for(let s=0;s<nSims;s++){
    let cum=1,acc=0; const base=s*nM;
    for(let m=0;m<nM;m++){cum*=(1+paths[base+m]); acc+=1/cum;}
    perRupee[s]=acc*cum; lump[s]=cum;
  }
  const m50=target/pct(perRupee,50), m80=target/pct(perRupee,20);
  const lumpNeed=target/pct(lump,50);
  const today=target/Math.pow(1+INFL,years);
  document.getElementById('g_out').innerHTML=`<div class="card">
    <p class="big">${rs(m50)}<span style="font-size:17px;color:var(--muted);font-weight:400"> / month</span></p>
    <p class="sub">for a roughly even chance · ${esc(label)}</p>
    <p class="stand">To reach <b>${rs(target)}</b> in ${years} years, saving
      <b>${rs(m50)}</b> a month gets there in about half of simulated histories.
      For a <b>four-in-five</b> chance you would need <b>${rs(m80)}</b> —
      ${((m80/m50-1)*100).toFixed(0)}% more. That difference is what certainty
      costs, and most calculators never show it.</p>
    <div class="caution"><b>${rs(target)} then is not ${rs(target)} now.</b>
      At ${(INFL*100).toFixed(1)}% inflation it will buy what about
      <b>${rs(today)}</b> buys today.</div>
    <table>
      <tr><td>Monthly, ~50% chance</td><td>${rs(m50)}</td></tr>
      <tr><td><b>Monthly, ~80% chance</b></td><td><b>${rs(m80)}</b></td></tr>
      <tr><td>Or a lump sum today</td><td>${rs(lumpNeed)}</td></tr>
      <tr><td>Total contributed (at ${rs(m50)}/mo)</td><td>${rs(m50*nM)}</td></tr>
      <tr><td>Target in today's money</td><td>${rs(today)}</td></tr>
    </table>
    <p class="foot">${esc(note)} · Not advice.</p></div>`;
}

/* ---------- portfolio: bucketing and stress, all client-side ---------- */
const BUCKETS={
  large_cap:{label:'Large-cap Indian equity',beta:0.95,vol:0.16,mid:false},
  mid_small_cap:{label:'Mid & small-cap Indian equity',beta:1.35,vol:0.24,mid:true},
  index_fund:{label:'Index fund / ETF',beta:1.00,vol:0.16,mid:false},
  gold:{label:'Gold',beta:-0.05,vol:0.15,mid:false},
  debt:{label:'Debt / FD / bonds',beta:0.05,vol:0.04,mid:false,dur:3.5},
  international:{label:'International equity',beta:0.75,vol:0.18,mid:false},
  cash:{label:'Cash',beta:0,vol:0,mid:false}
};
const SCEN=[
  {n:'Global Financial Crisis',p:'2008–09',eq:-0.55,mid:-0.15,rate:-150},
  {n:'COVID-19 Crash',p:'2020',eq:-0.38,mid:-0.10,rate:-100},
  {n:'IL&FS Credit Freeze',p:'2018–19',eq:-0.14,mid:-0.22,rate:50},
  {n:'Taper Tantrum',p:'2013',eq:-0.12,mid:-0.10,rate:300},
  {n:'Demonetisation',p:'2016',eq:-0.08,mid:-0.06,rate:-50},
  {n:'Hypothetical oil spike',p:'—',eq:-0.18,mid:-0.07,rate:150}
];
const WORDS=[['gold',['gold','sgb','silver','goldbees']],
 ['debt',['fd','fixed deposit','debt','bond','ppf','epf','nps','liquid','gilt','gsec','g-sec','recurring']],
 ['international',['us stock','us equity','s&p','nasdaq','international','global fund','foreign']],
 ['index_fund',['index fund','niftybees','nifty bees','etf','index']],
 ['cash',['cash','savings','idle']],
 ['mid_small_cap',['midcap','mid cap','smallcap','small cap','microcap','mid-cap','small-cap']]];
const LARGE=['reliance','tcs','hdfc','infosys','infy','icici','sbi','bharti','airtel','itc',
 'kotak','axis','larsen','bajaj','maruti','sun pharma','titan','wipro','nestle','hul','adani',
 'ntpc','ongc','coal india','tata','jsw','cipla','britannia','hero','hcl','tech mahindra'];
const MULT={lakh:1e5,lakhs:1e5,lac:1e5,lacs:1e5,l:1e5,crore:1e7,crores:1e7,cr:1e7,k:1e3,thousand:1e3};

function parseHoldings(text){
  const re=/(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr|k|thousand|l)?\s*(?:worth\s*)?(?:of\s+|in\s+|into\s+)\s*([a-z0-9&.\- ]{2,40}?)(?=\s*(?:,|and\b|;|\.|$))/gi;
  const out=[];let m;
  while((m=re.exec(text))!==null){
    const v=parseFloat(m[1].replace(/,/g,''))*(MULT[(m[2]||'').toLowerCase()]||1);
    if(!(v>=100))continue;
    let name=m[3].replace(/\b(worth|of|in|into|the|my|some|a)\b/gi,'').trim();
    if(name.length<2)continue;
    const low=name.toLowerCase();
    let bucket='large_cap',guessed=true;
    for(const [b,ws] of WORDS) if(ws.some(w=>low.includes(w))){bucket=b;guessed=false;break;}
    if(guessed && LARGE.some(c=>low.includes(c))){bucket='large_cap';guessed=false;}
    out.push({name:name.replace(/\b\w/g,c=>c.toUpperCase()),value:v,bucket,guessed});
  }
  return out;
}

function doPortfolio(){
  const hs=parseHoldings(document.getElementById('pf_text').value);
  const el=document.getElementById('pf_out');
  if(!hs.length){el.innerHTML=`<div class="card"><p class="stand">Couldn't read any
    holdings. Try "5 lakh in HDFC Bank and 3 lakh in gold".</p></div>`;return;}
  const total=hs.reduce((a,h)=>a+h.value,0);
  const w=hs.map(h=>h.value/total);
  const hhi=w.reduce((a,x)=>a+x*x,0);
  const top1=Math.max(...w);
  const sorted=[...w].sort((a,b)=>b-a);
  const top5=sorted.slice(0,5).reduce((a,x)=>a+x,0);
  // Volatility with a declared cross-asset correlation, not a measured one.
  const byB={};hs.forEach(h=>byB[h.bucket]=(byB[h.bucket]||0)+h.value/total);
  const keys=Object.keys(byB);const rho=0.6;
  let v=keys.reduce((a,b)=>a+Math.pow(byB[b]*BUCKETS[b].vol,2),0);
  for(let i=0;i<keys.length;i++)for(let j=i+1;j<keys.length;j++)
    v+=2*rho*byB[keys[i]]*BUCKETS[keys[i]].vol*byB[keys[j]]*BUCKETS[keys[j]].vol;
  const vol=Math.sqrt(Math.max(v,0));
  const stress=SCEN.map(s=>{
    let pnl=0;
    hs.forEach(h=>{const b=BUCKETS[h.bucket];
      pnl+=h.value*(b.beta*s.eq+(b.mid?s.mid:0))+h.value*(b.dur?-b.dur*s.rate/10000:0);});
    return {...s,pnl,pctv:pnl/total};
  }).sort((a,b)=>a.pnl-b.pnl);
  const unk=hs.filter(h=>h.guessed).map(h=>h.name);
  let h=`<div class="card">
    <p class="big">${rs(total)}</p>
    <p class="sub">across ${hs.length} holdings · effective spread ${(1/hhi).toFixed(1)} ways</p>
    <p class="stand">Your biggest single holding is <b>${(top1*100).toFixed(0)}%</b>
      of the total and the top five are <b>${(top5*100).toFixed(0)}%</b>. A typical
      year swings about <b>±${(vol*100).toFixed(0)}%</b>, so a normal year could land
      between <b>${rs(total*(1-1.65*vol))}</b> and <b>${rs(total*(1+1.65*vol))}</b>.
      The worst scenario in Indian market history — ${esc(stress[0].n)} — would have
      cost you <b>${(stress[0].pctv*100).toFixed(0)}%</b>, about ${rs(Math.abs(stress[0].pnl))}.</p>
    <div class="h3">What you hold</div><table>`;
  hs.forEach(x=>h+=`<tr><td>${esc(x.name)} <span class="pill">${esc(BUCKETS[x.bucket].label)}${x.guessed?' · assumed':''}</span></td><td>${rs(x.value)}</td></tr>`);
  h+=`</table><div class="h3">If history repeated</div><table>`;
  stress.forEach(s=>{const c=s.pctv<-0.3?'var(--yes)':s.pctv<-0.1?'var(--mid)':'var(--ink)';
    h+=`<tr><td>${esc(s.n)} <span class="pill">${esc(s.p)}</span></td><td style="color:${c}">${(s.pctv*100).toFixed(0)}% · ${rs(Math.abs(s.pnl))}</td></tr>`;});
  h+=`</table>`;
  if(unk.length) h+=`<div class="caution">Couldn't identify ${esc(unk.join(', '))} —
    treated as large-cap equity. Name the asset class to correct it.</div>`;
  h+=`<p class="foot">Individual shares cannot be priced here, so holdings are grouped
    by asset class and the class's typical behaviour applied. A concentrated position
    in one mid-cap is riskier than the mid-cap average and this will not show it.
    Correlation between classes is assumed at ${(rho*100).toFixed(0)}%, not measured.
    Nothing leaves your device.</p></div>`;
  el.innerHTML=h;
}

/* ---------- data-backed sections ---------- */
const NICE={REPO_RATE:'Repo rate',CRR:'Cash reserve ratio',SLR:'Statutory liquidity ratio',
 USDINR:'Rupees per US dollar',NIFTY50_CLOSE:'Nifty 50',BANKNIFTY_CLOSE:'Bank Nifty',
 INDIA_VIX:'India VIX',GOLD_USD:'Gold (USD/oz)',BRENT_USD:'Brent crude',
 SP500:'S&P 500',US_10Y:'US 10-year yield',DOLLAR_INDEX:'Dollar index',
 NIFTY_MIDCAP_CLOSE:'Nifty Midcap 100',FII_FPI_NET_CASH:'Foreign investors bought',
 DII_NET_CASH:'Indian institutions bought'};
const nice=k=>NICE[k]||k.replace(/_/g,' ').toLowerCase().replace(/^./,c=>c.toUpperCase());

async function load(){
  const get=async n=>{try{return await (await fetch('data/'+n+'.json',{cache:'no-store'})).json();}catch(e){return null;}};
  [D.returns,D.market,D.council,D.scoreboard,D.coverage]=await Promise.all(
    ['returns','market','council','scoreboard','coverage'].map(get));

  const opts=[];
  for(const [k,v] of Object.entries(D.returns?.assets||{})) opts.push(`<option value="${k}">${esc(v.label)}</option>`);
  for(const [k,v] of Object.entries(D.returns?.fixed||{})) opts.push(`<option value="${k}">${esc(v.label)}</option>`);
  document.getElementById('p_asset').innerHTML=opts.join('');
  document.getElementById('g_asset').innerHTML=opts.join('');

  const m=D.market;
  if(m?.series?.length){
    document.getElementById('m_as_of').textContent=
      'Recorded by a scheduled job. Last refreshed '+(m.as_of||'').slice(0,10)+'.';
    document.getElementById('m_out').innerHTML='<table>'+m.series.map(s=>
      `<tr><td>${esc(nice(s.series))}</td><td>${s.value.toLocaleString('en-IN',{maximumFractionDigits:2})}${s.unit==='pct'?'%':''}</td></tr>`).join('')+'</table>';
  } else document.getElementById('m_out').textContent='No snapshot available yet.';

  const c=D.council;
  document.getElementById('c_out').innerHTML = c?.runs?.length
    ? '<table>'+c.runs.slice(0,12).map(r=>
        `<tr><td>${esc(r.question)}<br><span class="pill">asked ${esc(r.asked)} · resolves ${esc(r.resolves)}</span></td>
         <td>${(r.probability*100).toFixed(0)}%</td></tr>`).join('')+'</table>'
    : 'No recorded verdicts yet.';

  const st=D.scoreboard?.standing;
  document.getElementById('s_out').innerHTML = (st && st.n_resolved)
    ? `<table><tr><td>Resolved questions</td><td>${st.n_resolved}</td></tr>
       <tr><td>Brier score</td><td>${st.brier.toFixed(4)}</td></tr>
       <tr><td>Skill vs base rate</td><td>${(st.skill_vs_base_rate*100).toFixed(1)}%</td></tr></table>
       <p class="foot">${esc(st.verdict)}</p>`
    : `<p class="sub">${esc(st?.verdict||'No resolved questions yet.')}</p>`;

  const cov=D.coverage?.by_asset_class;
  if(cov) document.getElementById('a_cov').innerHTML='<table>'+Object.entries(cov).map(([k,v])=>
    `<tr><td>${esc(k.replace(/_/g,' '))}</td><td style="color:${v.can_answer?'var(--no)':'var(--yes)'}">${v.can_answer?'covered':'no data'}</td></tr>`).join('')+'</table>';
}
load();
</script>
</body>
</html>
"""
