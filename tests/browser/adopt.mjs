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
  assert.equal(await p.eval("return document.querySelector('#reference-body > :first-child .outline-reference') !== null"), true);
  assert.deepEqual(await p.eval("return Array.from(document.querySelectorAll('.outline-reference h3'), h=>h.textContent)"), ["A. Screening","B. Results"]);
  assert.equal(await p.eval("return document.querySelectorAll('.reference-role strong').length"), 3);
  assert.match(side, /A‖B\(θ\)/);
  assert.match(side, /<literal>/);
  assert.equal(await p.eval("return Boolean(document.querySelector('.outline-reference literal'))"), false);

  // A reader can look back at paragraph two while typing paragraph three.
  for(let i=0;i<4;i++) await p.click('button.add[data-op="add"]');
  const third = '#author-form textarea[data-idx="2"]';
  await p.click(third);
  await p.type("Draft ");
  const y = await p.eval("return scrollY");
  await p.wheel("#reference-body", 420);
  assert.ok(await p.eval("return document.getElementById('reference-body').scrollTop") > 0);
  assert.equal(await p.eval("return scrollY"), y);
  assert.equal(await p.eval("return document.activeElement.matches("+JSON.stringify(third)+")"), true);
  await p.type("continues");
  assert.equal(await p.eval("return document.activeElement.value"), "Draft continues");
  const second='#author-form textarea[data-idx="1"]';
  await p.click(second);
  await p.type("Two ");
  const jump='[data-op="locate-reference"][data-i="1"]';
  assert.equal(await p.eval("return document.querySelector("+JSON.stringify(jump)+").hidden"), false);
  // P1 is repeated under both AI subheadings until the author assigns one.
  assert.equal(await p.eval('return document.querySelectorAll("[data-op=locate-reference]")[0].hidden'), true);
  await p.click(jump);
  assert.equal(await p.eval("return document.activeElement.matches("+JSON.stringify(second)+")"), true);
  await p.type("continued");
  assert.equal(await p.eval("return document.activeElement.value"), "Two continued");
  console.log("ok independent reference scrolling and retained writing focus");
  // Pasting stays blocked in the author's own plan.
  await p.click("#author-form textarea");
  const blocked = await p.eval(`const t=document.querySelector("#author-form textarea");const e=new ClipboardEvent("paste",{bubbles:true,cancelable:true,clipboardData:new DataTransfer()});e.clipboardData.setData("text/plain","copied");t.dispatchEvent(e);return e.defaultPrevented`);
  assert.equal(blocked, true);
  console.log("ok paste blocked in the paragraph plan");

  // The single save action keeps every paragraph editable.
  for(const index of [0,3,4]){
    await p.click(`#author-form textarea[data-idx="${index}"]`);
    await p.type("Role "+(index+1));
  }
  assert.equal(await p.eval('return document.querySelectorAll("#author-form button[type=submit]").length'), 1);
  await p.click("#author-form button.primary");
  await p.waitFor("document.getElementById('notice').textContent.length>0 && !document.getElementById('content').inert");
  await english("saved paragraph plan");
  await p.click(third);
  assert.equal(await p.eval("return document.activeElement.value"), "Draft continues");
  await p.eval("const t=document.activeElement; t.setSelectionRange(t.value.length,t.value.length)");
  await p.type(" edited");
  assert.equal(await p.eval("return document.activeElement.value"), "Draft continues edited");
  console.log("ok save preserves the editable paragraph plan");

  // Long roles are read in full; entering another row moves neither row, and only
  // the row being edited shows its frame and tools.
  await p.eval(`const t=document.querySelector('#author-form textarea[data-idx="0"]');t.focus();t.value="${"Long role sentence. ".repeat(40)}";t.dispatchEvent(new Event('input',{bubbles:true}));`);
  const fits = await p.eval(`return [...document.querySelectorAll('#plan-rows textarea')].every(t=>t.scrollHeight<=t.clientHeight+1)`);
  assert.equal(fits, true);
  const tops = `return [0,1].map(i=>Math.round(document.querySelector('#author-form textarea[data-idx="'+i+'"]').getBoundingClientRect().top))`;
  const before = await p.eval(tops);
  await p.click('#author-form textarea[data-idx="1"]');
  assert.deepEqual(await p.eval(tops), before);
  const tools = await p.eval(`return [...document.querySelectorAll('#plan-rows .plan-row')].map(r=>getComputedStyle(r.querySelector('.row-tools')).visibility)`);
  assert.equal(tools.filter(v=>v==="visible").length, 1);
  assert.equal(await p.eval(`return getComputedStyle(document.querySelector('#plan-rows .plan-row:focus-within .row-tools')).visibility`), "visible");
  console.log("ok rows grow with their text and stay put when the author moves between them");
} finally { p.close(); }
