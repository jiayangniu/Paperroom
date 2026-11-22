/* Real-browser checks for the whole-paper version reader and the review page. */
import {launch} from "./cdp.mjs";
import assert from "node:assert/strict";
// Usage: node compare.mjs <chrome> <base url> <intro section> <results section> <debug port>
// Seed: V0 (4 pages, results on page 3), V1 "导师会前" (5 pages, results on 4), V2 (6 pages, results on 5).
const [chrome,BASE,intro,results,port]=process.argv.slice(2);
const p=await launch(chrome,Number(port));
const log=(...a)=>console.log("ok",...a);
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const NOTE="第二段的转折还没写完，先回去看原文";
const spot=`const s=readSpot(manuscriptPages(manuscriptSide),manuscriptLine());return s&&(s.page+s.f)`;
const paneSpot=side=>`const b=document.querySelector('[data-pane=${side}] .reader-pages');const r=b.getBoundingClientRect();const s=readSpot(b.querySelectorAll('figure'),r.top+r.height/3);return s.page+s.f`;
const paneTop=side=>`const b=document.querySelector('[data-pane=${side}] .reader-pages');return readSpot(b.querySelectorAll('figure'),b.getBoundingClientRect().top+12).page`;
// Scroll a pane so its reading line sits at `at` (page index + fraction).
const scrollPane=(side,at)=>`const b=document.querySelector('[data-pane=${side}] .reader-pages');const f=b.querySelectorAll('figure')[${Math.floor(at)}].getBoundingClientRect();const r=b.getBoundingClientRect();b.scrollTop+=f.top+${at%1}*f.height-(r.top+r.height/3)`;
const loaded=sel=>`[...document.querySelectorAll('${sel} img')].every(i=>i.complete&&i.naturalWidth)`;
const panes=()=>p.eval("return [...document.querySelectorAll('.reader-pane')].map(n=>n.dataset.pane+':'+n.dataset.doc)");
try{
  // ---------- Desktop review page: the latest version, flipped against the one before ----------
  await p.viewport(1440,900);
  await p.goto(BASE+"view=review");
  await p.waitFor(loaded(".page-set"));
  assert.equal(await p.eval("return document.querySelector('.manuscript .page-bar h3').textContent"),"V2");
  const counts=await p.eval("return [document.querySelectorAll('.page-set[data-set=before] .page-frame').length,document.querySelectorAll('.page-set[data-set=after] .page-frame').length]");
  assert.deepEqual(counts,[5,6]);
  const flips=await p.eval("return [...document.querySelectorAll('[data-op=flip-manuscript]')].map(b=>b.innerText.replace(/\\s+/g,' '))");
  assert.deepEqual(flips,["上一版 V1 · 导师会前","这一版 V2"]);
  assert.deepEqual(await p.eval("return [...el('version-choice').options].map(o=>o.textContent)"),["V2","V1 · 导师会前","V0 · 原稿"]);
  log("review page shows V2 and flips against",flips[0],"pages",counts);
  // Start a note: pin on page 2 and type half an observation.
  await p.eval("document.querySelector('#page-2').scrollIntoView({block:'center',behavior:'instant'})");
  await p.click("#page-2 img");
  assert.equal(await p.eval("return model.fields.entry.page"),2);
  assert(await p.eval("return Boolean(model.fields.entry.pin && document.querySelector('#page-2 .mark.current'))"));
  await p.click("#note-body"); await p.type(NOTE);
  log("pinned page 2 of V2 and started a note");
  await p.eval("window.scrollTo({top:document.querySelector('#page-3').getBoundingClientRect().top+scrollY-200,behavior:'instant'})");
  const afterSpot=await p.eval(spot), afterY=await p.eval("return scrollY");
  await p.click('[data-op="flip-manuscript"][data-side="before"]');
  await p.waitFor("manuscriptSide==='before'");
  await pause(300);
  const beforeSpot=await p.eval(spot);
  assert(Math.abs(beforeSpot-afterSpot)<0.05,`mapped spot ${beforeSpot} vs ${afterSpot}`);
  assert.equal(await p.eval("return el('note-body').value"),NOTE);
  assert.equal(await p.eval("return model.fields.entry.page"),2);
  assert(await p.eval("return !el('baseline-note').hidden && document.querySelector('.page-set[data-set=after]').hidden"));
  log("flip to 上一版 kept spot",afterSpot.toFixed(3),"→",beforeSpot.toFixed(3),"and the half-typed note + page-2 marker");
  await p.click(".page-set[data-set=before] div.page-frame:nth-of-type(3) img");
  assert.equal(await p.eval("return model.fields.entry.page"),2,"baseline click must not move the marker");
  log("clicking the read-only 上一版 page does not move the marker");
  await p.click('[data-op="flip-manuscript"][data-side="after"]');
  await pause(300);
  const backY=await p.eval("return scrollY");assert(Math.abs(backY-afterY)<2,`${backY} vs ${afterY}`);
  log("flip back without scrolling: scrollY",afterY,"→",backY);
  await p.eval("window.scrollBy({top:500,behavior:'instant'})");
  const s2=await p.eval(spot);
  await p.click('[data-op="flip-manuscript"][data-side="before"]');
  await pause(300);
  const s3=await p.eval(spot);
  assert(Math.abs(s2-s3)<0.05);
  log("after reading on, 上一版 follows to",s3.toFixed(3),"(这一版 was",s2.toFixed(3)+")");
  await p.click('[data-op="flip-manuscript"][data-side="after"]');
  await p.click("#note-body"); await p.key("End"); await p.type("，补完。");
  assert.equal(await p.eval("return model.fields.entry.text"),NOTE+"，补完。");
  log("continued typing after flipping");

  // ---------- Desktop reader: all versions, latest beside the previous by default ----------
  assert.equal(await p.eval("return el('open-document-reader').textContent"),"排版版本");
  await p.click("#open-document-reader");
  await p.waitFor(loaded("#reader-panes"));
  // Each side's header: colour tag, then the picker showing the version's full name and date.
  const heads=await p.eval("return [...document.querySelectorAll('.reader-pane')].map(n=>n.dataset.pane+':'+n.querySelector('.version-tag').textContent+':'+n.querySelector('select.reader-picker').selectedOptions[0].textContent.replace(/ · \\d{4}-\\d\\d-\\d\\d$/,''))");
  assert.deepEqual(heads,["before:V1:V1 · 导师会前","after:V2:V2"]);
  assert.equal(await p.eval("return document.querySelector('input[name=reader-mode]:checked').value"),"compare");
  assert.equal(await p.eval("return el('reader-title').textContent"),"版本对照");
  assert(await p.eval("return Boolean(document.querySelector('[data-pane=after] .latest-badge'))&&!document.querySelector('[data-pane=before] .latest-badge')"));
  assert.match(await p.eval("return location.search"),/panel=versions.*before=1.*after=2.*mode=compare/);
  log("reader opens in 版本对照:",heads.join(" | "));
  // The author scrolls a side with the wheel; scripts then set the exact spot on that side.
  const lead=async(side,at)=>{await p.wheel(`[data-pane=${side}] .reader-pages`,1);await p.eval(scrollPane(side,at));await pause(400)};
  // By default each side scrolls on its own.
  assert.equal(await p.eval("return el('reader-sync').checked"),false);
  const L0=await p.eval(paneSpot("before"));
  await lead("after",4.5);
  assert(Math.abs(await p.eval(paneSpot("before"))-L0)<0.01);
  log("independent by default: V1 stays at",L0.toFixed(3),"while V2 moves");
  // Syncing follows the section, not the page number: V2 page 5 is V1 page 4.
  await p.click("#reader-sync");
  await lead("after",4.5);
  const L=await p.eval(paneSpot("before")),R=await p.eval(paneSpot("after"));
  assert(Math.abs(R-4.5)<0.05,`after pane at ${R}`);
  assert(Math.abs(L-3.5)<0.05,`sync ${L} ${R}`);
  log("同步滚动: V2 at",R.toFixed(3),"→ V1 at the same place in Results,",L.toFixed(3));
  // Either side can lead.
  await lead("before",3.2);
  assert(Math.abs(await p.eval(paneSpot("after"))-4.2)<0.05);
  log("V1 leads too: V2 follows to",(await p.eval(paneSpot("after"))).toFixed(3));
  await p.click("#reader-sync"); // off again
  await lead("after",4.4);
  const keepR=await p.eval(paneSpot("after"));
  // One version at a time: the latest, chosen with the picker or ←/→, at the same place.
  await p.click('label:has(input[name=reader-mode][value=single])');
  await pause(300);
  assert.deepEqual(await panes(),["only:v-2"]);
  const single=await p.eval(paneSpot("only"));
  assert(Math.abs(single-keepR)<0.02);
  assert.equal(await p.eval("return el('reader-title').textContent"),"排版版本");
  assert.equal(await p.eval("return getComputedStyle(el('reader-flip')).display==='none'||el('reader-flip').hidden"),true);
  log("单版本 opens on the latest, V2 at",single.toFixed(3));
  await p.eval("document.querySelector('#reader-panes .reader-pages').focus()");
  await p.key("ArrowLeft");
  await p.waitFor(`document.querySelector('.reader-pane')?.dataset.doc==='v-1'&&${loaded("#reader-panes")}`);
  await pause(300);
  const flipped=await p.eval(paneSpot("only"));
  assert(Math.abs(flipped-(single-1))<0.05,`← ${single} → ${flipped}`);
  assert.equal(await p.eval("return document.querySelector('.reader-pane .version-tag').textContent"),"V1");
  await p.eval("document.querySelector('#reader-panes .reader-pages').focus()");
  await p.key("ArrowRight");
  await p.waitFor("document.querySelector('.reader-pane')?.dataset.doc==='v-2'");
  await pause(300);
  assert(Math.abs(await p.eval(paneSpot("only"))-single)<0.05);
  log("← to V1 and → back to V2 stay in Results:",single.toFixed(3),"→",flipped.toFixed(3),"→ back");
  await p.click('label:has(input[name=reader-mode][value=compare])');
  await pause(300);
  assert(Math.abs(await p.eval(paneSpot("after"))-keepR)<0.02);
  log("back to 两版对照, still at the same spot");
  await p.click('[data-zoom=in]');
  await p.click('[data-zoom=in]');
  await pause(300);
  assert.equal(await p.eval("return el('reader-zoom-level').textContent"),"125%");
  assert(Math.abs(await p.eval(paneSpot("after"))-keepR)<0.03);
  log("zoom − % + steps to 125% and keeps the reading spot");
  await p.click('#reader-zoom-level');
  await pause(200);
  assert.equal(await p.eval("return el('reader-zoom-level').textContent"),"100%");
  await p.click("#close-reader");
  assert.equal(await p.eval("return document.activeElement.id"),"note-body");
  assert.equal(await p.eval("return el('note-body').value"),NOTE+"，补完。");
  assert.doesNotMatch(await p.eval("return location.search"),/panel=/);
  log("closing returns focus to the half-written note; text intact");
  await p.type("再加一句");
  assert.match(await p.eval("return model.fields.entry.text"),/再加一句$/);
  await p.click("#open-document-reader");
  await pause(500);
  assert(Math.abs(await p.eval(paneSpot("after"))-keepR)<0.03);
  log("reopening the reader restores the previous spot");
  // Each side chooses its own version; the earlier one stays on the left.
  await p.eval("const s=document.querySelector('[data-reader-side=before]');s.value='v-0';s.dispatchEvent(new Event('change',{bubbles:true}))");
  await p.waitFor("document.querySelector('[data-pane=before]')?.dataset.doc==='v-0'");
  assert.deepEqual(await panes(),["before:v-0","after:v-2"]);
  await p.eval("const s=document.querySelector('[data-reader-side=after]');s.value='v-1';s.dispatchEvent(new Event('change',{bubbles:true}))");
  await p.waitFor("document.querySelector('[data-pane=after]')?.dataset.doc==='v-1'");
  assert.deepEqual(await panes(),["before:v-0","after:v-1"]);
  // A version chosen on one side stays on that side.
  await p.eval("const s=document.querySelector('[data-reader-side=before]');s.value='v-2';s.dispatchEvent(new Event('change',{bubbles:true}))");
  await p.waitFor("document.querySelector('[data-pane=before]')?.dataset.doc==='v-2'");
  assert.deepEqual(await panes(),["before:v-2","after:v-1"]);
  // Choosing the version shown on the other side swaps the two.
  await p.eval("const s=document.querySelector('[data-reader-side=before]');s.value='v-1';s.dispatchEvent(new Event('change',{bubbles:true}))");
  await p.waitFor("document.querySelector('[data-pane=before]')?.dataset.doc==='v-1'");
  const swapped=await panes();
  assert.deepEqual(swapped,["before:v-1","after:v-2"]);
  assert.match(await p.eval("return location.search"),/before=1.*after=2/);
  log("each side keeps the version chosen for it; picking the other side's version swaps:",swapped.join(" | "));
  await p.click("#close-reader");
  assert.match(await p.eval("return model.fields.entry.text"),/再加一句$/);
  log("the unsent note survives choosing versions in the reader");

  // ---------- Submit the note on the latest version ----------
  await p.click('[data-op="add-note"]');
  await p.waitFor("document.querySelector('#annotations .comment')");
  assert.equal(await p.eval("return el('annotations').querySelector('.status').textContent.trim()"),"1 条");
  await p.click('[data-op="submit-review"]');
  await p.waitFor("el('notice').textContent.includes('本版审阅已提交')");
  assert.equal(await p.eval("return document.querySelector('#note-body')"),null);
  assert(await p.eval("return Boolean(document.querySelector('#page-2 .mark'))"));
  log("note with its page-2 pin submitted on V2");

  // ---------- A chat link names the pair to compare ----------
  await p.goto(BASE+"view=review&panel=versions&mode=compare&before=0&after=2");
  await p.waitFor("el('document-reader').open&&document.querySelectorAll('.reader-pane').length===2");
  assert.deepEqual(await panes(),["before:v-0","after:v-2"]);
  log("link with before=0&after=2 opens exactly that pair");
  await p.goto(BASE+"view=paper&panel=versions&mode=latest");
  await p.waitFor("el('document-reader').open&&document.querySelector('.reader-pane')");
  assert.deepEqual(await panes(),["only:v-2"]);
  log("link with mode=latest opens only the latest version");

  // ---------- Opened from a section: every version starts at that section's page ----------
  await p.goto(BASE+"view=section&section="+results);
  await p.waitFor("document.querySelector('#open-document-reader')");
  await p.click("#open-document-reader");
  await p.waitFor(loaded("#reader-panes"));
  await pause(400);
  const tops=[await p.eval(paneTop("before")),await p.eval(paneTop("after"))];
  assert.deepEqual(tops,[3,4],"V1 Results on page 4, V2 on page 5");
  log("reader from Results opens V1 at page",tops[0]+1,"and V2 at page",tops[1]+1);
  await p.click('label:has(input[name=reader-mode][value=single])');
  await p.eval("const s=document.querySelector('[data-reader-side=only]');s.value='v-1';s.dispatchEvent(new Event('change',{bubbles:true}))");
  await p.waitFor("document.querySelector('.reader-pane')?.dataset.doc==='v-1'");
  await p.click("#close-reader");
  await p.goto(BASE+"view=review&section="+results);
  await p.waitFor(loaded(".page-set[data-set=after]"));
  // The page's label starts just below the sticky version bar, not hidden under it.
  const below=`const bar=document.querySelector('.manuscript.has-baseline .page-bar').getBoundingClientRect().bottom;
    const label=el('page-5').previousElementSibling.getBoundingClientRect().top;return scrollY>0&&label>=bar&&label-bar<16`;
  await p.waitFor(`(()=>{${below}})()`,5000);
  const reviewTop=await p.eval("return readSpot(manuscriptPages('after'),document.querySelector('.manuscript .page-bar').getBoundingClientRect().bottom+12)?.page");
  assert.equal(reviewTop,4,"the review page starts at V2 page 5");
  log("review page from Results starts at page",reviewTop+1);

  // ---------- Mobile: compare flips between versions at the same place ----------
  await p.viewport(390,844,true);
  await p.goto(BASE+"view=review");
  await p.waitFor(loaded(".page-set"));
  await p.click("#open-document-reader");
  await p.waitFor(loaded("#reader-panes"));
  const m=await p.eval("return {flip:!el('reader-flip').hidden,vis:[...document.querySelectorAll('.reader-pane')].map(n=>n.dataset.pane+':'+getComputedStyle(n).visibility),docW:document.documentElement.scrollWidth}");
  assert.equal(m.flip,true);
  assert(m.docW<=390,`page wider than the phone: ${m.docW}`);
  log("mobile reader:",JSON.stringify(m));
  await p.eval(scrollPane("after",4.5));
  await pause(300);
  const mA=await p.eval(paneSpot("after"));
  await p.click('#reader-flip [data-flip=before]');
  await pause(300);
  const mB=await p.eval(paneSpot("before"));
  assert(Math.abs(mB-(mA-1))<0.05,`mobile ${mA} → ${mB}`);
  assert.equal(await p.eval("return getComputedStyle(document.querySelector('[data-pane=after]')).visibility"),"hidden");
  log("mobile flip V2→V1 lands in Results:",mA.toFixed(3),"→",mB.toFixed(3));
  const sl=await p.eval("return document.querySelector('[data-pane=after] .reader-pages').scrollTop");
  await p.click('#reader-flip [data-flip=after]');
  await pause(300);
  assert.equal(await p.eval("return document.querySelector('[data-pane=after] .reader-pages').scrollTop"),sl);
  log("flip back without scrolling returns to the exact scrollTop",sl);
  await p.click("#close-reader");
}finally{p.close()}
