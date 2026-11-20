/* Real-browser checks for the before/after reader and the review flip. */
import {launch} from "./cdp.mjs";
import assert from "node:assert/strict";
// Usage: node compare.mjs <chrome> <base url> <intro section> <single-document section> <debug port>
const [chrome,BASE,intro,res,port]=process.argv.slice(2);
const p=await launch(chrome,Number(port));
const log=(...a)=>console.log("ok",...a);
const spot=`const s=readSpot(manuscriptPages(manuscriptSide),manuscriptLine());return s&&(s.page+s.f)`;
try{
  // ---------- Desktop review page ----------
  await p.viewport(1440,900);
  await p.goto(BASE+"view=review&section="+intro);
  await p.waitFor("[...document.querySelectorAll('.page-set img')].every(i=>i.complete&&i.naturalWidth)");
  const counts=await p.eval("return [document.querySelectorAll('.page-set[data-set=before] .page-frame').length,document.querySelectorAll('.page-set[data-set=after] .page-frame').length]");
  log("review pages before/after",counts);
  // Start a note: pin on page 2 and type half an observation.
  await p.eval("document.querySelector('#page-2').scrollIntoView({block:'center',behavior:'instant'})");
  await p.click("#page-2 img");
  await p.click("#note-body"); await p.type("第二段的转折还没写完，先回去看原文");
  await p.eval("window.scrollTo({top:document.querySelector('#page-3').getBoundingClientRect().top+scrollY-200,behavior:'instant'})");
  const afterSpot=await p.eval(spot), afterY=await p.eval("return scrollY");
  await p.click('[data-op="flip-manuscript"][data-side="before"]');
  await p.waitFor("manuscriptSide==='before'");
  await new Promise(r=>setTimeout(r,300));
  const beforeSpot=await p.eval(spot);
  assert(Math.abs(beforeSpot-afterSpot)<0.05,`mapped spot ${beforeSpot} vs ${afterSpot}`);
  assert.equal(await p.eval("return el('note-body').value"),"第二段的转折还没写完，先回去看原文");
  assert.equal(await p.eval("return model.fields.entry.page"),2);
  assert(await p.eval("return !el('baseline-note').hidden && document.querySelector('.page-set[data-set=after]').hidden"));
  log("flip to 改前 kept spot",afterSpot.toFixed(3),"→",beforeSpot.toFixed(3),"and the half-typed note + page-2 marker");
  await p.click(".page-set[data-set=before] div.page-frame:nth-of-type(3) img");
  assert.equal(await p.eval("return model.fields.entry.page"),2,"baseline click must not move the marker");
  log("clicking the read-only 改前 page does not move the marker");
    await p.click('[data-op="flip-manuscript"][data-side="after"]');
  await new Promise(r=>setTimeout(r,300));
  const backY=await p.eval("return scrollY");assert(Math.abs(backY-afterY)<2,`${backY} vs ${afterY}`);log("flip back without scrolling: scrollY",afterY,"→",backY);
  // Read further in 改后, flip again: 改前 follows.
  await p.eval("window.scrollBy({top:500,behavior:'instant'})");
  const s2=await p.eval(spot);
  await p.click('[data-op="flip-manuscript"][data-side="before"]');
  await new Promise(r=>setTimeout(r,300));
  const s3=await p.eval(spot);
  assert(Math.abs(s2-s3)<0.05);
  log("after reading on, 改前 follows to",s3.toFixed(3),"(改后 was",s2.toFixed(3)+")");
  await p.click('[data-op="flip-manuscript"][data-side="after"]');
  await p.click("#note-body"); await p.key("End"); await p.type("，补完。");
  assert.equal(await p.eval("return model.fields.entry.text"),"第二段的转折还没写完，先回去看原文，补完。");
  log("continued typing after flipping, entry text =",await p.eval("return model.fields.entry.text"));

  // ---------- Desktop reader dialog ----------
  await p.click("#open-document-reader");
  await p.waitFor("[...document.querySelectorAll('#reader-panes img')].every(i=>i.complete&&i.naturalWidth)");
  const heads=await p.eval("return [...document.querySelectorAll('.reader-pane')].map(n=>n.dataset.pane+':'+n.querySelector('.version-tag').textContent+':'+n.querySelector('.version-name strong').textContent)");
  assert.deepEqual(heads,["before:改前:改写前的引言","after:改后:第 1 版成稿"]);
  log("reader opens side by side without choosing:",heads.join(" | "));
  const paneSpot=side=>`const b=document.querySelector('[data-pane=${side}] .reader-pages');const r=b.getBoundingClientRect();const s=readSpot(b.querySelectorAll('figure'),r.top+r.height/3);return s.page+s.f`;
  await p.eval("const b=document.querySelector('[data-pane=after] .reader-pages');b.scrollTop=b.scrollHeight*0.55");
  await new Promise(r=>setTimeout(r,400));
  const L=await p.eval(paneSpot("before")),R=await p.eval(paneSpot("after"));
  assert(Math.abs(L-R)<0.05,`sync ${L} ${R}`);
  log("同步滚动: right pane at",R.toFixed(3),"left followed to",L.toFixed(3));
  await p.click("#reader-sync"); // turn off
  await p.eval("const b=document.querySelector('[data-pane=after] .reader-pages');b.scrollTop=0");
  await new Promise(r=>setTimeout(r,300));
  assert(Math.abs(await p.eval(paneSpot("before"))-L)<0.01);
  log("sync off: left pane stays where it was");
  await p.click("#reader-sync");
  await p.eval("const b=document.querySelector('[data-pane=after] .reader-pages');b.scrollTop=b.scrollHeight*0.4");
  await new Promise(r=>setTimeout(r,300));
  const keepR=await p.eval(paneSpot("after"));
  // Switch to single and back: positions retained
  await p.click('label:has(input[name=reader-mode][value=single])');
  await new Promise(r=>setTimeout(r,300));
  const single=await p.eval(paneSpot("only"));
  assert(Math.abs(single-keepR)<0.02);
  log("单份阅读 keeps 改后 at",single.toFixed(3));
  // Desktop single reading: the 改前/改后 switch opens the other version at the same spot.
  assert.equal(await p.eval("return getComputedStyle(el('reader-flip')).display!=='none'&&el('reader-flip').querySelectorAll('button').length"),2);
  assert.equal(await p.eval("return document.querySelector('.reader-pane').dataset.version"),"after");
  await p.click('#reader-flip [data-flip=before]');
  await p.waitFor("document.querySelector('.reader-pane')?.dataset.version==='before'&&[...document.querySelectorAll('#reader-panes img')].every(i=>i.complete&&i.naturalWidth)");
  await new Promise(r=>setTimeout(r,300));
  const flipped=await p.eval(paneSpot("only"));
  assert(Math.abs(flipped-single)<0.05,`single flip ${single} → ${flipped}`);
  assert.equal(await p.eval("return document.querySelector('.reader-pane .version-tag').textContent"),"改前");
  await p.eval("document.querySelector('#reader-panes .reader-pages').focus()");
  await p.key("ArrowRight");
  await p.waitFor("document.querySelector('.reader-pane')?.dataset.version==='after'");
  await new Promise(r=>setTimeout(r,300));
  assert(Math.abs(await p.eval(paneSpot("only"))-single)<0.05);
  log("单份阅读 flip 改后→改前→改后 (button, then →) stays at",flipped.toFixed(3));
  await p.click('label:has(input[name=reader-mode][value=compare])');
  await new Promise(r=>setTimeout(r,300));
  assert(Math.abs(await p.eval(paneSpot("after"))-keepR)<0.02);
  log("back to 两版对照, still at the same spot");
  await p.click('label:has(input[name=reader-zoom][value="2"])');
  await new Promise(r=>setTimeout(r,300));
  assert(Math.abs(await p.eval(paneSpot("after"))-keepR)<0.03);
  log("zoom 2× keeps the reading spot");
  await p.click('label:has(input[name=reader-zoom][value="1"])');
  await p.click("#close-reader");
  assert.equal(await p.eval("return document.activeElement.id"),"note-body");
  assert.equal(await p.eval("return el('note-body').value"),"第二段的转折还没写完，先回去看原文，补完。");
  log("closing returns focus to the half-written note; text intact");
  await p.type("再加一句");
  assert.match(await p.eval("return model.fields.entry.text"),/再加一句$/);
  await p.click("#open-document-reader");
  await new Promise(r=>setTimeout(r,500));
  assert(Math.abs(await p.eval(paneSpot("after"))-keepR)<0.03);
  log("reopening the reader restores the previous spot");
  await p.click("#close-reader");

  // ---------- Importing keeps the unsent note ----------
  await p.click("#open-document-reader");
  await p.click("#toggle-import");
  await p.eval("el('reader-source').value='project';el('reader-source').dispatchEvent(new Event('change',{bubbles:true}));el('reader-path').value='before.pdf';el('reader-pages').value='1-2';el('reader-label').value='导入测试'");
  await p.click("#reader-save");
  await p.waitFor("el('reader-message').textContent==='参考稿已保存。'",20000);
  assert.equal(await p.eval("return document.querySelector('.reader-pane .version-name strong').textContent"),"导入测试");
  assert.match(await p.eval("return model.fields.entry.text"),/再加一句$/);
  log("importing an extra reference shows it and keeps the unsent note");
  await p.click("#close-reader");

  // ---------- Only one document ----------
  await p.goto(BASE+"view=section&section="+res);
  await p.waitFor("document.querySelector('#open-document-reader')");
  await p.click("#open-document-reader");
  await new Promise(r=>setTimeout(r,400));
  const alone=await p.eval("return {panes:document.querySelectorAll('.reader-pane').length,tag:document.querySelector('.version-tag').textContent,msg:el('reader-alone').textContent,modes:el('reader-modes').hidden,title:el('reader-title').textContent}");
  assert.equal(alone.panes,1); assert.equal(alone.modes,true);
  log("single document:",JSON.stringify(alone));
  await p.click("#close-reader");

  // ---------- Mobile ----------
  await p.viewport(390,844,true);
  await p.goto(BASE+"view=review&section="+intro);
  await p.waitFor("[...document.querySelectorAll('.page-set img')].every(i=>i.complete&&i.naturalWidth)");
  await p.click("#open-document-reader");
  await p.waitFor("[...document.querySelectorAll('#reader-panes img')].every(i=>i.complete&&i.naturalWidth)");
  const m=await p.eval("return {zoom:getComputedStyle(el('reader-panes')).getPropertyValue('--zoom'),flip:!el('reader-flip').hidden&&getComputedStyle(el('reader-flip')).display,vis:[...document.querySelectorAll('.reader-pane')].map(n=>n.dataset.pane+':'+getComputedStyle(n).visibility),dialog:[el('document-reader').offsetWidth,el('document-reader').offsetHeight],docW:document.documentElement.scrollWidth}");
  log("mobile reader:",JSON.stringify(m));
  await p.eval("const b=document.querySelector('[data-pane=after] .reader-pages');b.scrollTop=b.scrollHeight*0.6");
  await new Promise(r=>setTimeout(r,300));
  const mA=await p.eval(paneSpot("after"));
  await p.click('#reader-flip [data-flip=before]');
  await new Promise(r=>setTimeout(r,300));
  const mB=await p.eval(paneSpot("before"));
  assert(Math.abs(mA-mB)<0.05);
  assert.equal(await p.eval("return getComputedStyle(document.querySelector('[data-pane=after]')).visibility"),"hidden");
  log("mobile flip 改后→改前 lands on the same spot",mA.toFixed(3),"→",mB.toFixed(3));
  const sl=await p.eval("return document.querySelector('[data-pane=after] .reader-pages').scrollTop");
  await p.click('#reader-flip [data-flip=after]');
  await new Promise(r=>setTimeout(r,300));
  assert.equal(await p.eval("return document.querySelector('[data-pane=after] .reader-pages').scrollTop"),sl);
  log("flip back without scrolling returns to the exact scrollTop",sl);
  await p.click("#close-reader");
}finally{p.close()}
