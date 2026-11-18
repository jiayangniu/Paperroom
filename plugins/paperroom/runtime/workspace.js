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

/* Writing timestamps */
(() => {
  const dialog = el("time-journal");
  const list = el("journal-events");
  const status = el("journal-status");
  const authority = el("journal-authority");
  const labels = {
    paper_outline: "论文大纲已提交",
    section_outline: "章节段落大纲已提交",
    paragraph_outline: "段内逐句大纲已提交",
    section_published: "整节成稿已发布",
    section_reviewed: "整节审阅已提交"
  };
  let journal = null;
  let generation = 0;
  let pendingStamp = null;

  function message(text, error = false) {
    status.textContent = text;
    status.classList.toggle("error", error);
  }

  function timestamp(value) {
    if (!value || !/(Z|[+-]\d\d:\d\d)$/i.test(value)) return "时间未知";
    const date = new Date(value.replace(/(\.\d{3})\d+/, "$1"));
    if (Number.isNaN(date.getTime())) return "时间未知";
    const utc = date.toISOString();
    return '<time datetime="' + utc + '">' + utc.slice(0, 19).replace("T", " ") + ' UTC</time>';
  }

  function eventTitle(event) {
    const title = [labels[event.kind] || "写作记录"];
    if (event.section) {
      const section = [...arr(data?.outline?.sections), ...arr(data?.archived)].find(s => s.id === event.section);
      title.push(section?.title || event.section);
      if (event.paragraph) {
        const index = arr(section?.paragraphs).findIndex(p => p.id === event.paragraph);
        title.push(index < 0 ? event.paragraph : "现第 " + (index + 1) + " 段");
      }
    }
    if (event.revision != null) title.push("版本 " + event.revision);
    return esc(title.join(" · "));
  }

  function render(result) {
    journal = result;
    const events = result.events;
    authority.hidden = !events.length;
    authority.textContent = result.tsa_configured
      ? "申请时，Paperroom 会将该条记录的加盐摘要发送给 " + (result.authority || "配置的时间戳服务") + "。"
      : "当前未配置第三方时间戳服务，新提交会使用本机时间。";
    list.innerHTML = events.slice().reverse().map(event => {
      const receipt = event.receipt;
      const receiptLine = receipt
        ? '<p>第三方签发　' + timestamp(receipt.verified_at) + ' · ' + esc(receipt.authority || "时间戳服务") + '</p>'
        : '<p>第三方签发　尚无回执</p>';
      const action = !receipt && result.tsa_configured
        ? '<button type="button" class="secondary" data-stamp-seq="' + esc(event.seq) + '">申请第三方时间戳</button>' : "";
      return '<li><h3>' + eventTitle(event) + '</h3><p>本机记录　' + timestamp(event.recorded_at) + '</p>' + receiptLine + action + '</li>';
    }).join("");
    el("journal-export").hidden = !events.length;
    message(events.length ? "" : "还没有时间记录。从下一次提交大纲、发布整节成稿或提交审阅起，记录会显示在这里。旧稿保留原样，时间未知。");
  }

  async function readResponse(response) {
    if (response.ok) return response.json();
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.error || "请求失败，请重试。");
  }

  el("open-time-journal").addEventListener("click", async () => {
    const visit = ++generation;
    if (!dialog.open) dialog.showModal();
    list.innerHTML = "";
    journal = null;
    authority.hidden = true;
    el("journal-export").hidden = true;
    message("正在读取时间记录…");
    try {
      if (pendingStamp) await pendingStamp.catch(() => {});
      const response = await fetch("/api/timestamps", {cache: "no-store"});
      const result = await readResponse(response);
      if (visit === generation && dialog.open) render(result);
    } catch (error) {
      if (visit === generation && dialog.open) message("读取失败。 " + error.message, true);
    }
  });
  el("close-journal").addEventListener("click", () => dialog.close());

  list.addEventListener("click", async event => {
    const button = event.target.closest("button[data-stamp-seq]");
    if (!button || !journal?.tsa_configured || pendingStamp) return;
    const entry = journal.events.find(item => String(item.seq) === button.dataset.stampSeq);
    if (!entry || entry.receipt) return;
    const visit = generation;
    for (const action of list.querySelectorAll("button")) action.disabled = true;
    message("正在向时间戳服务申请回执…");
    pendingStamp = fetch("/api/timestamps", {
      method: "POST", headers: {"Content-Type": "application/json", "X-Paperroom-Token": window.roomToken},
      body: JSON.stringify({seq: entry.seq, digest: entry.digest})
    }).then(readResponse);
    try {
      const result = await pendingStamp;
      if (visit === generation && dialog.open) render(result);
    } catch (error) {
      if (visit === generation && dialog.open) {
        message("申请失败。 " + error.message, true);
        for (const action of list.querySelectorAll("button")) action.disabled = false;
      }
    } finally {
      pendingStamp = null;
    }
  });

  el("download-journal").addEventListener("click", async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const response = await fetch("/api/timestamps/export", {
        cache: "no-store", headers: {"X-Paperroom-Token": window.roomToken}
      });
      if (!response.ok) await readResponse(response);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "paperroom-timestamps.json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      if (dialog.open) message("下载失败。 " + error.message, true);
    } finally {
      button.disabled = false;
    }
  });
})();
