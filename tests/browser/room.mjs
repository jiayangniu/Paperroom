/* An open page outlives its room: it reconnects after a restart and reloads after an update.
   Usage: node room.mjs <chrome> <workspace url> <debug port> <newer version>
   Prints a marker after each stage and waits for "next" on stdin before the following one. */
import {launch} from "./cdp.mjs";
import {createInterface} from "node:readline";
const [chrome, url, port, newer] = process.argv.slice(2);
const lines = createInterface({input: process.stdin})[Symbol.asyncIterator]();
const next = async () => { await lines.next(); };
const p = await launch(chrome, Number(port));
try {
  await p.viewport(1300, 900);
  await p.goto(url);
  await p.waitFor("el('connection')?.textContent==='本地工作区' && window.paperroomVersion");
  await p.waitFor("document.title.startsWith(paperroomProject.name+' · '+paperroomProject.parent) && document.querySelector('.mast-tag').title===paperroomProject.path && new URL(location.href).searchParams.get('room')===paperroomProject.room");
  console.log("ready", await p.eval("return window.paperroomVersion"));
  await next();                                    // the room was stopped
  await p.waitFor("el('connection').textContent==='暂时离线'", 20000);
  console.log("offline");
  await next();                                    // the room was started again
  await p.waitFor("el('connection').textContent==='本地工作区'", 20000);
  console.log("reconnected");
  await next();                                    // a newer version took over
  await p.waitFor(`window.paperroomVersion===${JSON.stringify(newer)}`, 20000);
  console.log("reloaded", await p.eval("return window.paperroomVersion"));
} finally { p.close(); }
