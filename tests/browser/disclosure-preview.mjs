import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

// Run the actual author-dialog listeners with synthetic files. No external services.
const nodes = new Map();
function el(id) {
  if (!nodes.has(id)) nodes.set(id, {
    listeners: {}, dataset: {}, classList: {toggle() {}},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    fire(type) { return this.listeners[type]({target: this}); },
    click() { this.clicked = true; },
    querySelectorAll() { return [checkbox]; },
  });
  return nodes.get(id);
}
const checkbox = {checked: true, dataset: {discSeq: "1", discId: "__v1_payload__"}};
const esc = value => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const oldEvent = {schema: "paperroom.event.v1", seq: 1, kind: "section_reviewed",
                  payload: {notes: [{text: "old note <tag>", pin: {x: 0, y: 1}}]}};
const newEvent = {schema: "paperroom.event.v2", seq: 2, kind: "checkpoint_restored",
                  commitments: [{id: "commit", label: "存档备注"}],
                  disclosed: {commit: {content: "new note & consent", salt: "abc"}}};
const raw = JSON.stringify({format: "paperroom-log-v2", project_name: "paper <A>", events: [oldEvent, newEvent]})
                .replace('"x":0,"y":1', '"x":0.0,"y":1.0');
let requests = 0, downloaded, resolveFetch;
const ctx = {
  el, window: {roomToken: "local"}, document: {createElement: el}, Blob, console, esc,
  data: null, arr: value => Array.isArray(value) ? value : [],
  URL: {createObjectURL(blob) { downloaded=blob; return "blob:test"; }, revokeObjectURL() {}}, setTimeout() {},
  async fetch() {
    requests++;
    if (resolveFetch !== undefined) await new Promise(resolve => { resolveFetch=resolve; });
    return {ok:true, blob: async () => new Blob([raw])};
  }
};
const script = fs.readFileSync(process.argv[2], "utf8");
vm.runInNewContext(script.split("/* Writing timestamps */")[1].split("/* Prepared files")[0], ctx);
const preview = el("preview-log-btn"), box = el("log-preview-box"), download = el("download-verifiable-log");
await preview.fire("click");
assert.ok(!box.hidden);
assert.match(box.innerHTML, /公开原文条数<\/span> · 2/);
assert.ok(box.innerHTML.includes("old note &lt;tag&gt;"));
assert.ok(box.innerHTML.includes("new note &amp; consent"));
assert.ok(box.innerHTML.includes("paper &lt;A&gt;"));
assert.ok(!box.innerHTML.includes("<tag>"));
await download.fire("click");
assert.equal(requests, 1);
assert.equal(await downloaded.text(), raw);
checkbox.checked = false;
el("log-disclosures").fire("change");
assert.ok(box.hidden);
resolveFetch = null;
const pending = preview.fire("click");
assert.equal(typeof resolveFetch, "function");
checkbox.checked = true;
el("log-disclosures").fire("change");
resolveFetch();
await pending;
assert.ok(box.hidden);
assert.equal(preview.disabled, false);
assert.equal(download.disabled, false);
