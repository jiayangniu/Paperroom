/* Switch to English and look for untranslated interface text on every view. */
import {launch} from "./cdp.mjs";
import assert from "node:assert/strict";
const [chrome, base, section, paragraph, port] = process.argv.slice(2);
const p = await launch(chrome, Number(port));
const leftovers = new Map();
const collect = `
  const re=/[\\u3400-\\u9fff]/, out=[];
  const w=document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT|NodeFilter.SHOW_ELEMENT);
  while(w.nextNode()){const n=w.currentNode;
    if(n.nodeType===3){
      // In head-only text ("Paragraph 3 · <author purpose>") only the generated head must be English.
      const text=n.parentElement.closest("[data-tr=head]")?n.nodeValue.split(" · ")[0]:n.nodeValue;
      if(re.test(text)&&!n.parentElement.closest("textarea,script,style,[translate=no]")) out.push(n.nodeValue.trim()) }
    else for(const a of ["placeholder","aria-label","title","alt"]) if(n.getAttribute(a)&&re.test(n.getAttribute(a))&&!n.closest("[translate=no]")) out.push(a+": "+n.getAttribute(a));
  }
  return [...new Set(out)];`;
async function check(name) {
  await new Promise(r => setTimeout(r, 400));
  if (process.env.PAPERROOM_SHOTS) await p.shot(process.env.PAPERROOM_SHOTS + "/" + name.replace(/ /g, "-") + ".png");
  for (const text of await p.eval(collect)) leftovers.set(text, name);
}
try {
  await p.viewport(1300, 900);
  await p.goto(base + "?view=paper");
  await p.waitFor("document.querySelector('#language-toggle')?.textContent==='English'");
  await p.click("#language-toggle");
  await p.waitFor("document.documentElement.lang==='en' && document.querySelector('.heading')");
  console.log("ok switched:", await p.eval("return document.querySelector('h1').textContent"));
  for (const [name, query] of [["assets", "?view=assets"], ["paper", "?view=paper"], ["section", `?view=section&section=${section}`],
                               ["paragraph", `?view=paragraph&section=${section}&paragraph=${paragraph}`],
                               ["review", `?view=review&section=${section}`]]) {
    await p.goto(base + query);
    await p.waitFor("document.querySelector('.heading')");
    await check(name);
    if (name === "paper") {
      // The research question and evidence are the author's: shown as written.
      const refs = await p.eval("return document.querySelector('.ref-card').innerText");
      assert.match(refs, /保留/); assert.match(refs, /图 1/); assert.doesNotMatch(refs, /Figure 1/);
      console.log("ok author question and evidence untouched");
      const names = await p.eval("return [...document.querySelectorAll('.jump, .navitem')].map(b=>b.innerText)");
      assert.ok(names.filter(n => n.includes("研究问题")).length >= 2, names.join(" | "));
      assert.ok(!names.some(n => /(^|§\s*)Research question\s*(→)?$/.test(n.trim())), names.join(" | "));
      console.log("ok author section name kept in the contents and the jump links");
    }
    if (name === "section") {
      const fits = await p.eval("const a=document.querySelector('#plan-rows textarea'); a.value=('A longer outline paragraph. ').repeat(60); a.dispatchEvent(new Event('input',{bubbles:true})); return a.scrollHeight <= a.clientHeight+1;");
      assert.ok(fits, "long paragraph should be visible without internal scrolling");
    }
    if (name === "paragraph") {
      assert.equal(await p.eval("return document.querySelectorAll('.context-fold:not([open])').length"), 2);
      await p.click(".context-fold summary");
      assert.ok(await p.eval("return document.querySelector('.context-fold').open"));
      const role = await p.eval("return document.querySelector('.current-anchor').innerText");
      assert.match(role, /Role of this paragraph\s+保留/);
      console.log("ok paragraph purpose untouched next to an English label");
    }
  }
  await p.click('[data-op="flip-manuscript"][data-side="before"]');
  await check("review before");
  await p.click("#open-document-reader");
  await p.waitFor("document.querySelector('.reader-pane')");
  await check("reader");
  await p.click("#close-reader");
  await p.click("#open-section-assets");
  await p.waitFor("el('asset-file').options.length === 2 && !el('asset-view').hidden");
  assert.equal(await p.eval("return el('asset-directory').textContent"), "paperroom-assets/figures/");
  assert.equal(await p.eval("return document.querySelectorAll('#asset-tabs input').length"), 2);
  assert.deepEqual(await p.eval("return Array.from(el('asset-file').options, o=>o.text).sort()"), ["comparison.pdf", "原稿.png"]);
  assert.equal(await p.eval("return !!document.querySelector('#asset-browser textarea, #asset-browser form')"), false);

  async function chooseFile(name) {
    await p.eval(`const select=el('asset-file');select.value=[...select.options].find(o=>o.text === ${JSON.stringify(name)}).value;
                  select.dispatchEvent(new Event('change',{bubbles:true}));`);
  }
  await chooseFile("comparison.pdf");
  await p.waitFor("el('asset-preview').querySelector('iframe')?.src");
  const pdfUrl = await p.eval("return el('asset-preview').querySelector('iframe').src");
  assert.equal(pdfUrl.split("#")[0], await p.eval("return el('asset-original').href"));
  assert.match(pdfUrl, /[?&]v=[a-f0-9]{64}/);
  await chooseFile("原稿.png");
  await p.waitFor("el('asset-preview').querySelector('img')?.naturalWidth");
  const imgUrl = await p.eval("return el('asset-preview').querySelector('img').src");
  assert.equal(imgUrl, await p.eval("return el('asset-original').href"));
  await check("prepared figures");
  await p.click("#asset-refresh");
  await p.waitFor("!el('asset-refresh').disabled && el('asset-preview').querySelector('img')?.naturalWidth");
  assert.equal(await p.eval("return el('asset-preview').querySelector('img').src"), imgUrl);

  await p.click('label:has(input[value=tables])');
  assert.equal(await p.eval("return el('asset-directory').textContent"), "paperroom-assets/tables/");
  assert.deepEqual(await p.eval("return Array.from(el('asset-file').options, o=>o.text)"), ["保留.pdf"]);
  await p.waitFor("el('asset-preview').querySelector('iframe')?.src");
  const tableUrl = await p.eval("return el('asset-preview').querySelector('iframe').src");
  assert.equal(tableUrl.split("#")[0], await p.eval("return el('asset-original').href"));
  assert.match(tableUrl, /[?&]v=[a-f0-9]{64}/);
  assert.equal(await p.eval("return (await fetch(el('asset-original').href)).headers.get('Content-Type')"), "application/pdf");
  await check("prepared tables");
  await p.click("#close-assets");
  await p.click("#open-assets");
  await p.waitFor("!el('asset-refresh').disabled && !el('asset-view').hidden");
  assert.equal(await p.eval("return el('asset-archive').hidden"), true);
  const legacy = new URL(base);
  legacy.search = new URLSearchParams({view: "paper", panel: "figures", build: "1"});
  await p.goto(legacy.href);
  await p.waitFor("el('asset-original').getAttribute('href')==='/api/floats/1/pdf' && !el('asset-view').hidden");
  assert.equal(await p.eval("return new URL(location.href).searchParams.get('build')"), "1");
  await check("archived build");
  const pinned = await p.eval("return location.href");
  await p.goto(pinned);
  await p.waitFor("el('asset-browser').open && !el('asset-view').hidden && !el('asset-archive').hidden");
  assert.equal(await p.eval("return el('asset-preview').querySelector('img').getAttribute('src')"), "/api/floats/1/pages/1");
  await p.click("#asset-current");
  await p.waitFor("el('asset-archive').hidden && el('asset-directory').textContent === 'paperroom-assets/figures/' && !el('asset-view').hidden");
  assert.equal(await p.eval("return new URL(location.href).searchParams.has('build')"), false);
  await p.click("#close-assets");
  await p.click("#open-time-journal");
  await p.waitFor("document.querySelector('#journal-events li')");
  await check("journal");
  const found = [...leftovers].map(([text, where]) => where + " → " + text);
  assert.deepEqual(found, [], "untranslated:\n" + found.join("\n"));
  console.log("ok no Chinese interface text left");
} finally { p.close(); }
