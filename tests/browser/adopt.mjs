/* The author reads an AI-drafted paper outline, adopts it, then plans a section
   beside the AI's reference. */
import {launch} from "./cdp.mjs";
import assert from "node:assert/strict";
const [chrome, base, section, port, lang = "zh"] = process.argv.slice(2);
const en = lang === "en";
// No interface text may stay Chinese in English mode (author and AI content is marked translate="no").
const leftovers = `const re=/[\\u3400-\\u9fff]/,out=[];const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  while(w.nextNode()){const n=w.currentNode;if(re.test(n.nodeValue)&&!n.parentElement.closest("textarea,script,style,[translate=no]"))out.push(n.nodeValue.trim())}return out`;
async function english(name) {
  if (!en) return;
  await new Promise(r => setTimeout(r, 300));
  assert.deepEqual(await p.eval(leftovers), [], name);
}
const p = await launch(chrome, Number(port));
const text = sel => p.eval(`return document.querySelector(${JSON.stringify(sel)})?.innerText||""`);
try {
  await p.viewport(1300, 900);
  await p.goto(base + `?view=section&section=${section}`);
  await p.waitFor("document.querySelector('.heading')");
  assert.match(await text("#content"), en ? /Adopt the sections first/ : /先采用章节安排/);
  await english("section before adoption");
  assert.equal(await p.eval("return Boolean(document.getElementById('author-form'))"), false);
  console.log("ok paragraph plan closed before adoption");
  await p.click('button[data-view="paper"].jump');
  await p.waitFor("document.querySelector('[data-op=adopt]')");
  const card = await text(".adopt-card");
  assert.match(card, en ? /Waiting: Introduction, Method/ : /待采用：Introduction、Method/);
  await english("paper outline with a draft");
  console.log("ok draft shown for adoption");
  await p.click("[data-op=adopt]");
  await p.waitFor("!document.querySelector('.adopt-card')");
  console.log("ok adopted");
  await p.goto(base + `?view=section&section=${section}`);
  await p.waitFor("document.getElementById('author-form')");
  const side = await text("#reference-body");
  assert.match(side, en ? /The AI's reference/ : /AI 的参考/);
  await english("section beside the reference");
  assert.match(side, /Motivate the cost of exact evaluations/);
  console.log("ok paragraph plan open beside the AI's reference");
  // Pasting stays blocked in the author's own plan.
  await p.click("#author-form textarea");
  const blocked = await p.eval(`const t=document.querySelector("#author-form textarea");const e=new ClipboardEvent("paste",{bubbles:true,cancelable:true,clipboardData:new DataTransfer()});e.clipboardData.setData("text/plain","copied");t.dispatchEvent(e);return e.defaultPrevented`);
  assert.equal(blocked, true);
  console.log("ok paste blocked in the paragraph plan");
} finally { p.close(); }
