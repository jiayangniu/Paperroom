// Minimal Chrome DevTools Protocol driver for headless interaction checks.
import {spawn} from "node:child_process";
import {mkdtempSync, writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";

export async function launch(chrome, port = 9333) {
  const profile = mkdtempSync(join(process.env.PAPERROOM_BROWSER_TMP || tmpdir(), "chrome-"));
  const proc = spawn(chrome, ["--headless=new", "--remote-debugging-port=" + port, "--user-data-dir=" + profile,
    "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "--disable-gpu", "--disable-dev-shm-usage",
    "about:blank"], {stdio: "ignore"});
  let target;
  // Slow or busy machines can take a while to bring up headless Chrome.
  for (let i = 0; i < 300 && !target; i++) {
    await new Promise(r => setTimeout(r, 100));
    try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find(t => t.type === "page"); } catch {}
  }
  if (!target) throw Error("Chrome did not start");
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  let id = 0; const waiting = new Map(), events = [];
  ws.onmessage = m => {
    const msg = JSON.parse(m.data);
    if (msg.id && waiting.has(msg.id)) { const {r, j} = waiting.get(msg.id); waiting.delete(msg.id); msg.error ? j(Error(msg.error.message)) : r(msg.result); }
    else if (msg.method) events.push(msg);
  };
  const send = (method, params = {}) => new Promise((r, j) => { const n = ++id; waiting.set(n, {r, j}); ws.send(JSON.stringify({id: n, method, params})); });
  await send("Page.enable"); await send("Runtime.enable");
  const page = {
    send, events,
    async eval(expr) {
      const res = await send("Runtime.evaluate", {expression: `(async()=>{${expr}})()`, awaitPromise: true, returnByValue: true});
      if (res.exceptionDetails) throw Error(res.exceptionDetails.exception?.description || res.exceptionDetails.text);
      return res.result.value;
    },
    async viewport(width, height, mobile = false) {
      await send("Emulation.setDeviceMetricsOverride", {width, height, deviceScaleFactor: mobile ? 3 : 1, mobile});
      if (mobile) await send("Emulation.setTouchEmulationEnabled", {enabled: true});
    },
    async goto(url) {
      await send("Page.navigate", {url});
      await page.waitFor("document.readyState==='complete'");
    },
    async waitFor(cond, ms = 20000) {
      const end = Date.now() + ms;
      while (Date.now() < end) { if (await page.eval("return Boolean(" + cond + ")")) return; await new Promise(r => setTimeout(r, 50)); }
      throw Error("timeout: " + cond);
    },
    async click(selector) {
      const box = await page.eval(`const n=document.querySelector(${JSON.stringify(selector)});if(!n)throw Error("missing "+${JSON.stringify(selector)});let r=n.getBoundingClientRect();const cy=r.top+r.height/2;if(cy<0||cy>innerHeight){n.scrollIntoView({block:"nearest",behavior:"instant"});r=n.getBoundingClientRect()}return {x:r.left+r.width/2,y:r.top+r.height/2}`);
      for (const type of ["mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", {type, x: box.x, y: box.y, button: "left", clickCount: 1});
      await new Promise(r => setTimeout(r, 120));
    },
    async type(text) { await send("Input.insertText", {text}); },
    async key(key, code = key) {
      for (const type of ["keyDown", "keyUp"]) await send("Input.dispatchKeyEvent", {type, key, code});
    },
    async wheel(selector, dy) {
      const box = await page.eval(`const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}`);
      await send("Input.dispatchMouseEvent", {type: "mouseWheel", x: box.x, y: box.y, deltaX: 0, deltaY: dy});
      await new Promise(r => setTimeout(r, 250));
    },
    async shot(path) {
      const {data} = await send("Page.captureScreenshot", {format: "png"});
      writeFileSync(path, Buffer.from(data, "base64"));
    },
    close() { ws.close(); proc.kill(); }
  };
  return page;
}
