/* A version that only answers notes: the author sees each answer and can approve or discuss. */
import {launch} from "./cdp.mjs";
import assert from "node:assert/strict";
const [chrome, url, port] = process.argv.slice(2);
const p = await launch(chrome, Number(port));
try {
  await p.viewport(1300, 900);
  await p.goto(url);
  await p.waitFor("document.querySelector('.response-list')");
  const answer = await p.eval("return document.querySelector('.response .answer').innerText");
  assert.match(answer, /有不同意见/);
  assert.match(answer, /The clause carries the scope/);
  assert.match(await p.eval("return document.querySelector('.manuscript').innerText"), /本版段落文字与上一版相同/);
  assert(await p.eval("return Boolean(document.querySelector('[data-op=approve-review]'))"));
  assert(await p.eval("return Boolean(document.querySelector('#note-body'))"));
  console.log("ok answer shown without text changes; author can approve or reply");
} finally { p.close(); }
