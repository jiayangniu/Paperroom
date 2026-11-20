/* Second-round review: answers to earlier notes, change summary and approval. */
import {launch} from "./cdp.mjs";
import assert from "node:assert/strict";
const [chrome, url, port] = process.argv.slice(2);
const p = await launch(chrome, Number(port));
const log = (...a) => console.log("ok", ...a);
try {
  await p.viewport(1300, 900);
  await p.goto(url);
  await p.waitFor("document.querySelector('.response-list')");
  const answers = await p.eval("return [...document.querySelectorAll('.response')].map(r=>r.querySelector('.answer-tag')?.textContent+'|'+r.querySelector('.answer').textContent)");
  assert.equal(answers.length, 2);
  assert.match(answers[0], /^已修改\|已修改.*Narrowed/);
  assert.match(answers[1], /^有不同意见\|/);
  assert(await p.eval("return document.querySelector('details.responses').open"));
  log("previous notes shown with answers:", answers.join(" / "));
  const summary = await p.eval("return [...document.querySelectorAll('.manuscript .form-hint')].map(n=>n.textContent).join(' ')");
  assert.match(summary, /本版改动了第 2 段/);
  log("change summary:", summary.split("。")[0]);
  assert.equal(await p.eval("return el('annotations').querySelector('.status').textContent.trim()"), "0 / 1 条");
  await p.eval("window.confirm=()=>true");
  await p.click('[data-op="approve-review"]');
  await p.waitFor("el('notice').textContent.includes('已提交')");
  await p.waitFor("document.querySelector('#annotations .notice')");
  log("approved without new notes:", await p.eval("return document.querySelector('#annotations .notice').textContent"));
  await p.eval("el('version-choice').value='1';el('version-choice').dispatchEvent(new Event('change',{bubbles:true}))");
  await p.click("#open-document-reader");
  await p.waitFor("document.querySelector('.reader-pane[data-doc=\"rev-2\"]')");
  const panes=await p.eval("return [...el('reader-panes').querySelectorAll('.reader-pane')].map(pane=>pane.dataset.doc)");
  assert.deepEqual(panes,["rev-1","rev-2"]);
  assert.equal(await p.eval("return el('reader-panes').querySelector('[data-reader-side]')===null"),true);
  log("section comparison from an earlier review opens the current pair");
} finally { p.close(); }
