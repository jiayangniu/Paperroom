/* Read-only reference pages are kept outside the editing form so toggling a
   version or importing an old draft preserves typed outlines and review notes. */
(() => {
  "use strict";
  const reader = el("document-reader");
  const form = el("reader-import");
  const panels = el("reader-panes");
  const mode = name => reader.querySelector('input[name="reader-mode"][value="'+name+'"]');
  let section = "", documents = [], left = "", right = "", comparing = false;
  let generation = 0;

  function documentLabel(doc) {
    const index = doc.id.split("-").pop();
    const versionText = doc.kind === "edition" ? "成稿 "+index : "参考稿 "+index;
    return [versionText, doc.title, (doc.created || "").slice(0,10)].filter(Boolean).join(" · ");
  }

  function pane(id, side, caption) {
    const doc = documents.find(item => item.id === id);
    if (!doc) return "";
    const options = documents.map(item => '<option value="'+esc(item.id)+'"'+
      (item.id===id?' selected':'')+'>'+esc(documentLabel(item))+'</option>').join("");
    const original = doc.pdf_url
      ? '<a href="'+esc(doc.pdf_url)+'" target="_blank" rel="noopener">打开 PDF</a>'
      : '<small>旧版仅存页图</small>';
    const name = documentLabel(doc);
    const pages = Array.from({length:doc.pages},(_,i) => '<figure><figcaption>第 '+(i+1)+' / '+doc.pages+
      ' 页</figcaption><img loading="lazy" src="'+esc(doc.page_url)+String(i+1)+'" alt="'+
      esc(name)+'，第 '+(i+1)+' 页"></figure>').join("");
    return '<section class="reader-pane"><header class="reader-pane-head"><label>'+caption+
      '<select data-reader-side="'+side+'">'+options+'</select></label>'+original+
      '</header><div class="reader-pages" role="region" aria-label="'+esc(caption+'，'+name)+'" tabindex="0">'+pages+'</div></section>';
  }

  function draw() {
    mode("single").checked = !comparing;
    mode("compare").checked = comparing;
    mode("compare").disabled = documents.length < 2;
    panels.classList.toggle("compare", comparing);
    panels.innerHTML = documents.length ? (comparing
      ? pane(left,"left","左稿")+pane(right,"right","右稿") : pane(right,"right","查看版本"))
      : '<p class="empty">本节还没有排版稿。可以先导入已有论文，之后发布的成稿也会出现在这里。</p>';
  }

  function setDocuments(items, preferred) {
    documents = items;
    const ids = items.map(item => item.id);
    if (!ids.includes(right) || preferred) right = preferred || ids.at(-1) || "";
    if (!ids.includes(left) || left === right) left = ids.filter(id => id !== right).at(-1) || "";
    if (ids.length < 2) comparing = false;
    draw();
  }

  function message(txt="", failed=false) {
    const status=el("reader-message");
    status.textContent=txt; status.classList.toggle("error",failed);
  }
  function showImport(open) {
    form.hidden=!open;
    el("toggle-import").setAttribute("aria-expanded",String(open));
  }
  function selectSource() {
    const upload=el("reader-source").value==="file";
    el("reader-upload-label").hidden=!upload; el("reader-path-label").hidden=upload;
    el("reader-path-hint").hidden=upload;
    el("reader-upload").disabled=!upload; el("reader-path").disabled=upload;
    el("reader-path").required=!upload;
  }
  function openReader() {
    section=route.section;
    ++generation;
    const sectionData=sec()||archived();
    el("reader-section").textContent=sectionData?.title||"";
    const items=arr(data.review?.documents);
    const selected=route.view==="review"&&currentRev()?"rev-"+currentRev().revision:"";
    right=items.some(item=>item.id===selected)?selected:"";
    left=""; comparing=false;
    form.reset(); selectSource(); el("reader-fields").disabled=false;
    el("toggle-import").hidden=!sec();
    showImport(!items.length && Boolean(sec()));
    message();
    setDocuments(items);
    reader.showModal();
  }

  document.addEventListener("click", e=>{
    if (e.target.closest("#open-document-reader")) openReader();
  });
  el("close-reader").addEventListener("click",()=>reader.close());
  reader.addEventListener("close",()=>{
    ++generation;
    section="";
    el("open-document-reader")?.focus({preventScroll:true});
  });
  el("toggle-import").addEventListener("click",()=>{
    showImport(form.hidden);
    if (!form.hidden) el("reader-source").focus();
  });
  el("reader-source").addEventListener("change",selectSource);
  reader.addEventListener("change", e=>{
    if (e.target.name==="reader-mode") {
      comparing=e.target.value==="compare" && documents.length>1;
      draw();
      return;
    }
    const side=e.target.dataset.readerSide;
    if (!side) return;
    const id=e.target.value;
    if (side==="left") {
      if (right===id) right=left;
      left=id;
    } else {
      if (left===id) left=right;
      right=id;
    }
    draw();
    panels.querySelector('[data-reader-side="'+side+'"]')?.focus({preventScroll:true});
  });

  form.addEventListener("submit",async e=>{
    e.preventDefault();
    if (el("reader-fields").disabled) return;
    const targetSection=section, request=generation;
    const title=el("reader-label").value.trim(), pages=el("reader-pages").value.trim()||"all";
    const headers={"X-Paperroom-Token":window.roomToken};
    let url, body;
    if (el("reader-source").value==="file") {
      body=el("reader-upload").files[0];
      if (!body) {message("请选择编译好的 PDF 文件。",true);return}
      if (body.size>32*1024*1024) {message("请选择不超过 32 MiB 的 PDF。",true);return}
      const params=new URLSearchParams({title:title||body.name,pages});
      url="/api/sections/"+encode(targetSection)+"/references?"+params;
      headers["Content-Type"]="application/pdf";
    } else {
      const path=el("reader-path").value.trim();
      if (!/\.(tex|pdf)$/i.test(path)) {message("请输入论文目录内的 .tex 或 .pdf 文件路径。",true);return}
      const key=/\.tex$/i.test(path)?"tex":"pdf";
      url="/api/workspace";
      body=JSON.stringify({action:"reference",section:targetSection,title:title||path.split("/").pop(),pages,[key]:path});
      headers["Content-Type"]="application/json";
    }
    el("reader-fields").disabled=true;
    message("正在准备排版稿…");
    try {
      const response=await fetch(url,{method:"POST",headers,body});
      const changed=await response.json();
      if (!response.ok) throw Error(changed.error||"导入失败。");
      if (request!==generation || targetSection!==route.section) return;
      const items=arr(changed.review?.documents);
      const newRef=items.find(doc=>doc.id===changed.reference_id);
      if (!newRef) throw Error("请重新打开章节参考稿，检查导入结果。");
      // Keep the local author model and its optimistic-lock version intact.
      if (data.review) data.review.documents=items;
      setDocuments(items,newRef.id);
      form.reset(); selectSource(); showImport(false);
      message("参考稿已保存。");
    } catch (err) {
      if (request===generation) message(err.message||"导入失败，请重试。",true);
    } finally {
      if (request===generation) el("reader-fields").disabled=false;
    }
  });

  window.addEventListener("popstate",()=>{if (reader.open) reader.close()});
})();
