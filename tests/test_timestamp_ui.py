"""Exercise the journal dialog separately from the author's unsaved work."""
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TimestampDialogTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to dispatch browser events.")
    def test_read_stamp_retry_and_download(self):
        harness = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const nodes = new Map();
function el(id) {
    if (!nodes.has(id)) nodes.set(id, {
        listeners:{}, dataset:{}, classList:{toggle(){}},
        addEventListener(type, listener){ this.listeners[type]=listener; },
        fire(type,target=this){ return this.listeners[type]({target,currentTarget:this}); },
        showModal(){this.open=true},close(){this.open=false},
        querySelectorAll(){return [stamp]},click(){this.clicked=true},
    });
    return nodes.get(id);
}
const calls=[];
let reply, ok=true;
const ctx = {
    el,window:Object.assign(el("window"),{roomToken:"sample"}),document:el("document"),
    data:{outline:{sections:[{id:"s1",title:"Intro",paragraphs:[{id:"p1"}]}]}},
    arr:x=>Array.isArray(x)?x:[],esc:x=>String(x).replace(/</g,"&lt;"),
    URL:{createObjectURL:()=>"blob:test",revokeObjectURL(){}},setTimeout(){},
    fetch:async(url,options)=>{calls.push({url,options});return {ok,json:async()=>reply,blob:async()=>({})}},
};
ctx.document.createElement=id=>el(id);
const stamp=el("stamp");
stamp.dataset.stampSeq="2";
stamp.closest=()=>stamp;
vm.runInNewContext(fs.readFileSync(process.argv[1],"utf8"),ctx);
(async()=>{
    const open = el("open-time-journal"), list=el("journal-events");
    const download=el("download-journal"),status=el("journal-status");
    assert.equal(calls.length,0);
    reply={tsa_configured:false,events:[]};
    await open.fire("click");
    assert.match(status.textContent,/还没有时间记录/);
    assert.equal(list.innerHTML,"");
    assert(el("journal-export").hidden);
    el("close-journal").fire("click");
    const first={seq:1,kind:"paper_outline",recorded_at:"2026-11-18T00:00:00.123456Z",digest:"a",receipt:null};
    const second={seq:2,kind:"paragraph_outline",section:"s1",paragraph:"p1",recorded_at:"2026-11-18T09:10:11+08:00",digest:"b",receipt:null};
    reply={tsa_configured:false,events:[first,second]};
    await open.fire("click");
    assert.match(list.innerHTML,/01:10:11 UTC/);
    assert.match(list.innerHTML,/逐句大纲已提交 · Intro · 现第 1 段/);
    assert(list.innerHTML.indexOf("逐句大纲") < list.innerHTML.indexOf("论文大纲"));
    assert(!list.innerHTML.includes("data-stamp-seq"));
    reply={...reply,tsa_configured:true,authority:"service.example"};
    await open.fire("click");
    assert.match(el("journal-authority").textContent,/service.example/);
    assert.match(list.innerHTML,/data-stamp-seq="2"/);
    assert(calls.every(call=>call.url==="/api/timestamps"&&call.options.method===undefined));
    const unsealed=reply;
    ok=false;reply={error:"服务超时"};
    await list.fire("click",stamp);
    assert(!stamp.disabled);
    assert.match(status.textContent,/服务超时/);
    assert.match(list.innerHTML,/尚无回执/);
    ok=true;reply={...unsealed,events:[first,{...second,receipt:{verified_at:"2026-11-18T09:10:20Z",authority:"service.example"}}]};
    await list.fire("click",stamp);
    const request=calls.at(-1);
    assert.equal(request.url,"/api/timestamps");
    assert.equal(request.options.method,"POST");
    assert.equal(request.options.headers["X-Paperroom-Token"],"sample");
    assert.deepEqual(JSON.parse(request.options.body),{seq:2,digest:"b"});
    assert.match(list.innerHTML,/第三方签发　<time[^>]+>2026-11-18 09:10:20 UTC<\/time> · service.example/);
    assert(!list.innerHTML.includes('data-stamp-seq="2"'));
    await download.fire("click");
    assert.equal(calls.at(-1).url,"/api/timestamps/export");
    assert.equal(calls.at(-1).options.headers["X-Paperroom-Token"],"sample");
    assert.equal(el("a").download,"paperroom-timestamps.json");
    assert(el("a").clicked);
})().catch(error=>{console.error(error);process.exitCode=1});
"""
        subprocess.run(["node", "-e", harness, str(ROOT / "plugins/paperroom/runtime/workspace.js")],
                       check=True, text=True)


if __name__ == "__main__":
    unittest.main()
