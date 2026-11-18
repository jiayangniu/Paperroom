"""Dispatch the production reader's UI events without running a local browser server."""
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DocumentReaderTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to dispatch browser events.")
    def test_browse_compare_import_and_preserve_author_text(self):
        harness = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const nodes = new Map();
function el(id) {
    if (!nodes.has(id)) nodes.set(id, {
        listeners:{}, dataset:{}, value:"", hidden:false, disabled:false, classList:{toggle(){}},
        focus(){},reset(){},showModal(){this.open=true},setAttribute(){},
        addEventListener(name,fn){this.listeners[name]=fn},querySelector(key){return el(key)},
        fire(type,target=this){return this.listeners[type]({target,preventDefault(){}})},
    });
    return nodes.get(id);
}
function version(id,title,n,pdf) {
    return {id,title,pages:n,kind:id.startsWith("rev")?"edition":"reference",
        created:"2026-11-18",page_url:"/"+id+"/pages/",pdf_url:pdf?"/"+id+"/pdf":null};
}
const ref=version("ref-1","初稿",2,true), old=version("rev-1","旧版",1,false);
const route={section:"s1",view:"review"};
const data={review:{documents:[ref,old]}};
const authorModel={fields:{items:["typed but unsaved"]},dirty:true};
const calls=[];
let reply;
const ctx = {
    el,document:el("document"),window:Object.assign(el("window"),{roomToken:"token"}),
    sec:()=>({title:"Intro"}),archived:()=>null,route,data,model:authorModel,
    arr:x=>Array.isArray(x)?x:[],esc:x=>String(x),encode:encodeURIComponent,URLSearchParams,
    currentRev:()=>({revision:1}),
    fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>reply}},
};
vm.runInNewContext(fs.readFileSync(process.argv[1],"utf8"),ctx);
(async()=>{
    const reader=el("document-reader"), panes=el("reader-panes"), form=el("reader-import");
    el("document").fire("click",{closest:()=>true});
    assert(reader.open);
    assert.match(panes.innerHTML,/旧版仅存页图/);
    assert.match(panes.innerHTML,/src="\/rev-1\/pages\/1"/);
    reader.fire("change",{name:"reader-mode",value:"compare",dataset:{}});
    assert.match(panes.innerHTML,/href="\/ref-1\/pdf"/);
    assert.match(panes.innerHTML,/src="\/ref-1\/pages\/2"/);
    assert.doesNotMatch(panes.innerHTML,/src="\/rev-1\/pages\/2"/);
    const labels=()=>[...panes.innerHTML.matchAll(/option value="([^"]+)" selected/g)].map(m=>m[1]);
    assert.deepEqual(labels(),["ref-1","rev-1"]);
    reader.fire("change",{dataset:{readerSide:"left"},value:"rev-1"});
    assert.deepEqual(labels(),["rev-1","ref-1"]);
    el("reader-source").value="project";el("reader-path").value="paper.tex";el("reader-pages").value="2-3";
    reply={reference_id:"ref-2",review:{documents:[ref,old,version("ref-2","修订稿",2,true)]}};
    await form.fire("submit");
    assert.deepEqual(JSON.parse(calls[0].options.body),{action:"reference",section:"s1",title:"paper.tex",pages:"2-3",tex:"paper.tex"});
    assert.match(panes.innerHTML,/src="\/ref-2\/pages\/1"/);
    el("reader-source").value="file";
    const file={name:"intro.pdf",size:123};
    el("reader-upload").files=[file];el("reader-pages").value="";
    reply={reference_id:"ref-3",review:{documents:[...reply.review.documents,version("ref-3","上传版本",1,true)]}};
    await form.fire("submit");
    assert.match(calls[1].url,/^\/api\/sections\/s1\/references\?/);
    assert.equal(calls[1].options.body,file);
    assert.equal(calls[1].options.headers["X-Paperroom-Token"],"token");
    assert.deepEqual(authorModel,{fields:{items:["typed but unsaved"]},dirty:true});
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        subprocess.run(["node", "-e", harness, str(ROOT / "plugins/paperroom/runtime/workspace.js")],
                       check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
