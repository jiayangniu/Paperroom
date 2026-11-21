/* Second-round review of a whole-paper version: answers to earlier notes, change summary and approval. */
import {launch} from "./cdp.mjs";
import assert from "node:assert/strict";
// Usage: node iteration.mjs <chrome> <base url> <debug port>
const [chrome, BASE, port] = process.argv.slice(2);
const p = await launch(chrome, Number(port));
const log = (...a) => console.log("ok", ...a);
try {
  await p.viewport(1300, 900);
  await p.goto(BASE + "view=review");
  await p.waitFor("document.querySelector('.response-list')");
  assert.equal(await p.eval("return document.querySelector('.manuscript .page-bar h3').textContent"), "V2 · 第二轮");
  const answers = await p.eval("return [...document.querySelectorAll('.response')].map(r=>r.querySelector('.answer-tag')?.textContent+'|'+r.querySelector('.answer').textContent)");
  assert.equal(answers.length, 2);
  assert.match(answers[0], /^已修改\|已修改.*Narrowed/);
  assert.match(answers[1], /^有不同意见\|.*No survey/);
  assert(await p.eval("return document.querySelector('details.responses').open"));
  const targets = await p.eval("return [...document.querySelectorAll('.response .note-target')].map(n=>n.textContent)");
  assert.match(targets[0], /Introduction 第 2 段/);
  assert.match(targets[1], /第 1 页/);
  log("previous notes shown with answers:", answers.join(" / "));
  const summary = await p.eval("return [...document.querySelectorAll('.manuscript .form-hint')].map(n=>n.textContent).join(' ')");
  assert.match(summary, /相对上一版有改动：Introduction 第 2 段/);
  log("change summary:", summary.split("。")[0]);
  assert.equal(await p.eval("return el('annotations').querySelector('.status').textContent.trim()"), "0 条");
  assert.deepEqual(await p.eval("return [...document.querySelectorAll('[data-op=flip-manuscript] b')].map(b=>b.textContent)"), ["上一版", "这一版"]);
  log("no minimum count; flip offers 上一版 / 这一版");
  await p.eval("window.confirm=()=>true");
  await p.click('[data-op="approve-review"]');
  await p.waitFor("el('notice').textContent.includes('已提交')");
  await p.waitFor("document.querySelector('#annotations .notice')");
  log("approved without new notes:", await p.eval("return document.querySelector('#annotations .notice').textContent"));
  assert.equal(await p.eval("return document.querySelector('[data-op=approve-review]')"), null);
  // An earlier version opens read-only with the notes it received.
  await p.eval("el('version-choice').value='1';el('version-choice').dispatchEvent(new Event('change',{bubbles:true}))");
  await p.waitFor("document.querySelector('.manuscript .page-bar h3')?.textContent==='V1'");
  assert.equal(await p.eval("return document.querySelectorAll('#annotations .comment').length"), 2);
  assert.equal(await p.eval("return document.querySelector('#note-body')"), null);
  log("V1 shows its two submitted notes, read-only");
  // The reader still opens on the latest pair, each side with its own version choice.
  await p.click("#open-document-reader");
  await p.waitFor("document.querySelector('.reader-pane[data-doc=\"v-2\"]')");
  const panes = await p.eval("return [...el('reader-panes').querySelectorAll('.reader-pane')].map(pane=>pane.dataset.doc+':'+pane.querySelector('[data-reader-side]')?.dataset.readerSide)");
  assert.deepEqual(panes, ["v-1:before", "v-2:after"]);
  log("reader from an earlier version opens the latest pair:", panes.join(" | "));
} finally { p.close(); }
