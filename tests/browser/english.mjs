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
    }
    if (name === "paragraph") {
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
  await p.click("#open-assets");
  await p.waitFor("document.querySelector('.float-card')");
  for (const tab of ["figures", "tables", "images", "data"]) {
    await p.click(`label:has(input[value=${tab}])`);
    await check("assets " + tab);
  }
  const cells = await p.eval("return [...document.querySelectorAll('.asset-table td')].map(c=>c.textContent)");
  assert.deepEqual(cells, ["保留", "图 1"]);
  assert.equal(await p.eval("return el('float-rebuild').textContent"), "Recompile");
  console.log("ok CSV cells untouched, buttons in English");
  await p.click("#close-assets");
  await p.click("#open-time-journal");
  await p.waitFor("document.querySelector('#journal-events li')");
  await check("journal");
  const found = [...leftovers].map(([text, where]) => where + " → " + text);
  assert.deepEqual(found, [], "untranslated:\n" + found.join("\n"));
  console.log("ok no Chinese interface text left");
} finally { p.close(); }
