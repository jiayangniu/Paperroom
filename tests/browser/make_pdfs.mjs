/* Print two six-page sections whose paragraphs sit at matching positions. */
import {launch} from "./cdp.mjs";
import {writeFileSync} from "node:fs";
import {join} from "node:path";
// Usage: node make_pdfs.mjs <chrome> <output dir> <debug port>
const [chrome,out,port]=process.argv.slice(2);
const p=await launch(chrome,Number(port));
function html(tag){
  let body="<h1>Introduction ("+tag+")</h1>";
  if(tag==="AFTER") body+="<p>Screening reduces exact evaluations in paired runs.</p><p>A common stopping rule is needed for a larger comparison.</p>";
  for(let i=1;i<=24;i++) body+=`<p><b>${tag} paragraph ${i}.</b> `+"Screening reduces exact evaluations in paired runs under a common stopping rule. ".repeat(i%3?4:7)+"</p>";
  return "<html><body style='font:15px/1.6 Georgia;margin:0'>"+body+"</body></html>";
}
for(const tag of ["BEFORE","AFTER"]){
  await p.goto("data:text/html;charset=utf-8,"+encodeURIComponent(html(tag)));
  const {data}=await p.send("Page.printToPDF",{paperWidth:6.9,paperHeight:9.6,marginTop:0.8,marginBottom:0.8,marginLeft:0.8,marginRight:0.8});
  writeFileSync(join(out,tag.toLowerCase()+".pdf"),Buffer.from(data,"base64"));
}
p.close();
