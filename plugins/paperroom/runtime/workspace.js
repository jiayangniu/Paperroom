/* Read-only reference pages are kept outside the editing form so flipping
   versions or importing an old draft preserves typed outlines and review notes.
   Desktop shows before and after side by side; narrow screens stack the two
   panes and flip between them at the same reading spot. */
(() => {
  "use strict";
  const reader = el("document-reader");
  const form = el("reader-import");
  const panels = el("reader-panes");
  const flipBar = el("reader-flip");
  const mode = name => reader.querySelector('input[name="reader-mode"][value="'+name+'"]');
  const narrow = window.matchMedia ? window.matchMedia("(max-width:720px)") : {matches:false};
  let section = "", documents = [], before = "", after = "", single = "", comparing = false;
  let showing = "after", zoom = 1, syncScroll = true, drawn = "", lastField = null;
  let generation = 0, spots = new Map(), arrived = null, quiet = null;
  const memory = new Map();

  function remembered(key, fallback) {
    try { const v = localStorage.getItem("paperroom-reader:"+key); return v === null ? fallback : JSON.parse(v); }
    catch { return fallback; }
  }
  function remember(key, value) {
    try { localStorage.setItem("paperroom-reader:"+key, JSON.stringify(value)); } catch {}
  }
  syncScroll = remembered("sync", true) !== false;

  const byId = id => documents.find(item => item.id === id);
  function created(doc) { return String(doc?.created || ""); }
  function order(a, b) {
    return created(a).localeCompare(created(b)) || (a.kind === b.kind ? 0 : a.kind === "reference" ? -1 : 1) ||
      documentNumber(a) - documentNumber(b);
  }
  function documentLabel(doc) {
    const kind = doc.kind === "edition" ? "成稿 "+documentNumber(doc) : "参考稿 "+documentNumber(doc);
    return [kind, doc.title, created(doc).slice(0,10)].filter(Boolean).join(" · ");
  }
  function detail(doc) {
    return [doc.kind === "edition" ? doc.title : "参考稿", created(doc).slice(0,10)].filter(Boolean).join(" · ");
  }
  function tag(doc, side) {
    if (side === "before") return "改前";
    if (side === "after") return "改后";
    if (doc.id === before && after) return "改前";
    if (doc.id === after && before) return "改后";
    return doc.kind === "edition" ? "成稿" : "原稿";
  }

  function pane(doc, side) {
    const caption = tag(doc, side);
    const name = versionName(doc);
    const options = documents.map(item => '<option value="'+esc(item.id)+'"'+(item.id===doc.id?' selected':'')+'>'+
      esc(documentLabel(item))+'</option>').join("");
    const swappable = comparing ? documents.length > 2 : documents.length > 1;
    const swap = swappable ? '<label class="reader-swap"><span>换一份</span><select data-reader-side="'+side+
      '" aria-label="更换'+esc(caption)+'显示的版本">'+options+'</select></label>' : "";
    const pdf = doc.pdf_url
      ? '<a href="'+esc(doc.pdf_url)+'" target="_blank" rel="noopener">打开 PDF</a>'
      : '<small>旧版仅存页图</small>';
    const pages = Array.from({length:doc.pages}, (_, i) => '<figure><figcaption>'+esc(caption)+' · 第 '+(i+1)+' / '+
      doc.pages+' 页</figcaption><img src="'+esc(doc.page_url)+String(i+1)+'" alt="'+esc(caption+"，"+name)+'，第 '+(i+1)+
      ' 页"></figure>').join("");
    return '<section class="reader-pane" data-pane="'+side+'" data-doc="'+esc(doc.id)+'"><header class="reader-pane-head">'+
      '<span class="version-tag '+(caption==="改前"?"before":caption==="改后"?"after":"")+'">'+esc(caption)+'</span>'+
      '<span class="version-name"><strong>'+esc(name)+'</strong><small>'+esc(detail(doc))+'</small></span>'+
      '<span class="reader-tail"><span class="page-count" aria-hidden="true">共 '+doc.pages+' 页</span>'+pdf+'</span>'+swap+
      '</header><div class="reader-pages" role="region" aria-label="'+esc(caption+"，"+name)+'" tabindex="0">'+pages+'</div></section>';
  }

  /* Spots are kept per document so returning to a version lands where it was left. */
  const scroller = side => panels.querySelector('[data-pane="'+side+'"] .reader-pages');
  const paneDoc = side => panels.querySelector('[data-pane="'+side+'"]')?.dataset.doc;
  const figures = box => box ? box.querySelectorAll("figure") : [];
  function line(box) { const r = box.getBoundingClientRect(); return r.top + r.height/3; }
  function spotOf(box) {
    if (!box || !box.getBoundingClientRect().height) return null;
    const spot = readSpot(figures(box), line(box));
    if (spot) spot.x = box.scrollWidth > box.clientWidth ? (box.scrollLeft + box.clientWidth/2)/box.scrollWidth : 0.5;
    return spot;
  }
  async function place(box, spot) {
    if (!box) return;
    if (!spot) {
      // Enlarged pages open centred, which crops the margins and keeps the text column.
      await pagesReady(figures(box), 0);
      box.scrollLeft = (box.scrollWidth - box.clientWidth) / 2;
      return;
    }
    quiet = box;
    await placeSpot(figures(box), spot, line(box), dy => { box.scrollTop += dy; });
    if (box.scrollWidth > box.clientWidth) box.scrollLeft = (spot.x ?? 0.5)*box.scrollWidth - box.clientWidth/2;
    requestAnimationFrame(() => { if (quiet === box) quiet = null; });
  }
  function saveSpots() {
    for (const node of panels.querySelectorAll(".reader-pane")) {
      const spot = spotOf(node.querySelector(".reader-pages"));
      if (spot) spots.set(node.dataset.doc, spot);
    }
  }
  function sides() { return comparing ? ["before","after"] : ["only"]; }
  function visibleSide() { return comparing ? (narrow.matches ? showing : "after") : "only"; }

  function paint() {
    mode("single").checked = !comparing;
    mode("compare").checked = comparing;
    mode("compare").disabled = documents.length < 2;
    el("reader-modes").hidden = documents.length < 2;
    panels.classList.toggle("compare", comparing);
    panels.dataset.showing = showing;
    panels.style.setProperty("--zoom", String(zoom));
    for (const side of ["before","after"]) {
      const node = panels.querySelector('[data-pane="'+side+'"]');
      if (node) node.inert = comparing && narrow.matches && side !== showing;
    }
    const pair = comparing && byId(before) && byId(after);
    flipBar.hidden = !pair;
    flipBar.innerHTML = pair ? ["before","after"].map(side => '<button type="button" data-flip="'+side+'" aria-pressed="'+
      (showing===side)+'"><b>'+(side==="before"?"改前":"改后")+'</b><span>'+esc(versionName(byId(side==="before"?before:after)))+
      '</span></button>').join("") : "";
    el("reader-sync-label").hidden = !comparing;
    el("reader-sync").checked = syncScroll;
    for (const input of reader.querySelectorAll('input[name="reader-zoom"]')) input.checked = Number(input.value) === zoom;
    el("reader-title").textContent = comparing ? "改前 / 改后对照" : "章节排版稿";
    el("reader-alone").textContent = aloneMessage();
    el("reader-alone").hidden = !aloneMessage();
  }
  function aloneMessage() {
    if (documents.length !== 1) return "";
    return documents[0].kind === "reference"
      ? "本节目前只有这一份原稿。AI 发布改写后的版本后，这里会自动左右对照。"
      : "这一版之前没有保存原稿排版，因此只显示这一份。";
  }

  async function draw() {
    const ids = comparing ? [before, after] : [single];
    const key = (comparing ? "c:" : "s:") + ids.join("|") + ":" + documents.map(d => d.id).join(",");
    if (key !== drawn) {
      saveSpots();
      drawn = key;
      panels.innerHTML = !documents.length
        ? '<p class="empty">本节还没有排版稿。改写已有章节时，AI 会先保存原稿排版，发布的新版也会出现在这里。</p>'
        : comparing ? pane(byId(before),"before")+pane(byId(after),"after") : pane(byId(single),"only");
      paint();
      await Promise.all(sides().map(side => place(scroller(side), spots.get(paneDoc(side)))));
    } else paint();
    updateCounts();
  }

  function updateCounts() {
    for (const node of panels.querySelectorAll(".reader-pane")) {
      const box = node.querySelector(".reader-pages"), count = node.querySelector(".page-count");
      const spot = box && box.getBoundingClientRect().height ? readSpot(figures(box), line(box)) : null;
      const total = figures(box).length;
      if (count && total) count.textContent = spot ? "第 "+(spot.page+1)+" / "+total+" 页" : "共 "+total+" 页";
    }
  }

  async function flip(side) {
    if (!comparing || side === showing) return;
    const from = scroller(showing), now = spotOf(from);
    const stayed = arrived?.side === showing && spotDistance(arrived.spot, now) < 0.03;
    if (now) spots.set(paneDoc(showing), now);
    showing = side;
    paint();
    const target = scroller(side);
    // Visiting the other version without scrolling returns exactly where it was;
    // after reading on, the other version follows to the matching spot.
    if (!stayed || !spots.get(paneDoc(side))) await place(target, now);
    arrived = {side, spot: spotOf(target)};
    updateCounts();
    flipBar.querySelector('[data-flip="'+side+'"]')?.focus({preventScroll:true});
  }

  function chronological(a, b) {
    const pair = [byId(a), byId(b)].sort(order);
    before = pair[0].id; after = pair[1].id;
  }

  function setDocuments(items, preferred) {
    documents = items.slice().sort(order);
    const ids = documents.map(item => item.id);
    if (preferred && ids.includes(preferred)) single = preferred;
    if (!ids.includes(single)) single = after && ids.includes(after) ? after : ids.at(-1) || "";
    if (documents.length < 2) comparing = false;
    if (comparing && !(ids.includes(before) && ids.includes(after) && before !== after)) {
      const other = ids.filter(id => id !== single).at(-1);
      chronological(other, single);
    }
    return draw();
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

  function stash() {
    if (!section) return;
    saveSpots();
    memory.set(section, {pair:before+"|"+after, comparing, showing, single, zoom, spots:new Map(spots)});
  }

  function openReader() {
    section=route.section;
    ++generation;
    const sectionData=sec()||archived();
    el("reader-section").textContent=sectionData?.title||"";
    const items=arr(data.review?.documents);
    const revision=route.view==="review"&&currentRev()?currentRev().revision:0;
    const pair=pairedVersions(items,revision);
    after=pair.after?.id||""; before=pair.before?.id||""; single=after;
    comparing=Boolean(pair.before);
    showing="after"; zoom=narrow.matches?1.3:1; spots=new Map(); arrived=null; drawn="";
    // Reopening the same pair returns to the same versions, layout and spots.
    const saved=memory.get(section);
    if (saved && saved.pair===before+"|"+after) {
      ({comparing, showing, zoom} = saved);
      single=saved.single; spots=new Map(saved.spots);
    }
    form.reset(); selectSource(); el("reader-fields").disabled=false;
    el("toggle-import").hidden=!sec();
    showImport(false);
    message();
    reader.showModal();
    setDocuments(items);
  }

  document.addEventListener("focusin", e => {
    if (e.target.closest?.("#note-editor, #author-form")) lastField = e.target;
  });
  document.addEventListener("click", e=>{
    if (e.target.closest("#open-document-reader")) openReader();
  });
  el("close-reader").addEventListener("click",()=>reader.close());
  reader.addEventListener("close",()=>{
    stash();
    ++generation;
    section="";
    // Return to the half-written observation so the author can keep typing.
    const fine=window.matchMedia?.("(pointer:fine)").matches;
    const target=fine&&lastField?.isConnected?lastField:el("open-document-reader");
    target?.focus({preventScroll:true});
  });
  el("toggle-import").addEventListener("click",()=>{
    showImport(form.hidden);
    if (!form.hidden) el("reader-source").focus();
  });
  el("reader-source").addEventListener("change",selectSource);
  flipBar.addEventListener("click", e => {
    const button = e.target.closest("[data-flip]");
    if (button) flip(button.dataset.flip);
  });
  reader.addEventListener("keydown", e => {
    if (!comparing || !narrow.matches || e.target.matches("input,select,textarea")) return;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      flip(e.key === "ArrowLeft" ? "before" : "after");
    }
  });
  reader.addEventListener("change", async e=>{
    if (e.target.name==="reader-mode") {
      saveSpots();
      comparing=e.target.value==="compare" && documents.length>1;
      if (comparing && !(byId(before)&&byId(after))) chronological(documents.filter(d=>d.id!==single).at(-1).id, single);
      if (!comparing) single = showing==="before"&&byId(before) ? before : single;
      await draw();
      return;
    }
    if (e.target.name==="reader-zoom") {
      saveSpots();
      zoom=Number(e.target.value)||1;
      paint();
      await Promise.all(sides().map(side => place(scroller(side), spots.get(paneDoc(side)))));
      updateCounts();
      return;
    }
    if (e.target.id==="reader-sync") {
      syncScroll=e.target.checked; remember("sync", syncScroll);
      return;
    }
    const side=e.target.dataset.readerSide;
    if (!side) return;
    const id=e.target.value;
    if (side==="only") single=id;
    else {
      const keep = side==="before" ? after : before;
      chronological(keep===id ? (side==="before" ? before : after) : keep, id);
    }
    await draw();
    panels.querySelector('[data-reader-side="'+side+'"]')?.focus({preventScroll:true});
  });

  let ticking = false;
  panels.addEventListener("scroll", e => {
    const box = e.target;
    if (!box.classList?.contains("reader-pages")) return;
    if (quiet === box) return;
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      ticking = false;
      updateCounts();
      if (!comparing || !syncScroll || narrow.matches) return;
      const side = box.closest(".reader-pane").dataset.pane;
      const other = scroller(side === "before" ? "after" : "before");
      const spot = spotOf(box);
      if (!other || !spot) return;
      quiet = other;
      placeSpot(figures(other), spot, line(other), dy => { other.scrollTop += dy; })
        .then(() => requestAnimationFrame(() => { if (quiet === other) quiet = null; }));
    });
  }, true);
  narrow.addEventListener?.("change", () => { if (reader.open) { paint(); updateCounts(); } });

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
      comparing=false;
      await setDocuments(items,newRef.id);
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
    paper_outline_proposed: "AI 草拟了章节安排",
    paper_outline_adopted: "作者采用了章节安排",
    section_hint: "AI 给出了段落安排参考",
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

/* Figures, tables and data: the real pages where each float lands, the author's
   instructions for the AI and their own confirmations. Nothing here gates drafting. */
(() => {
  "use strict";
  const dialog = el("asset-browser");
  const grid = el("asset-grid");
  const tabs = el("asset-tabs");
  const groups = [["figures", "论文中的图"], ["tables", "论文中的表"], ["images", "未放入论文的图片"], ["data", "数据文件"]];
  const names = {figure: "图", table: "表"};
  let index = null, active = "figures", visit = 0, busy = false;

  function status(text, error = false) {
    el("assets-status").textContent = text;
    el("assets-status").classList.toggle("error", error);
  }
  const currentTitle = () => (sec() || archived())?.title || "";
  const floatsOf = () => [...index.figures, ...index.tables];
  const titleOf = item => names[item.kind] + " " + item.number + (item.label ? " · " + item.label : "");
  const when = value => {
    const date = new Date(value || "");
    return Number.isNaN(date.getTime()) ? "" : date.toLocaleString([], {month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit"});
  };

  // Pages and PDF figures carry wide white margins: trim them so the content reads larger.
  function trim(img) {
    if (img.dataset.trimmed || !img.naturalWidth) return;
    img.dataset.trimmed = "1";
    const canvas = document.createElement("canvas");
    const w = canvas.width = img.naturalWidth, h = canvas.height = img.naturalHeight;
    const ctx = canvas.getContext("2d", {willReadFrequently: true});
    ctx.drawImage(img, 0, 0);
    let pixels;
    try { pixels = ctx.getImageData(0, 0, w, h).data; } catch { return; }
    let top = h, left = w, bottom = -1, right = -1;
    for (let y = 0; y < h; y += 2) for (let x = 0; x < w; x += 2) {
      const i = (y * w + x) * 4;
      if (pixels[i + 3] > 16 && (pixels[i] < 235 || pixels[i + 1] < 235 || pixels[i + 2] < 235)) {
        if (y < top) top = y; if (y > bottom) bottom = y; if (x < left) left = x; if (x > right) right = x;
      }
    }
    if (bottom < 0) return;
    const pad = Math.round(Math.min(w, h) * 0.02);
    top = Math.max(0, top - pad); left = Math.max(0, left - pad);
    bottom = Math.min(h, bottom + pad); right = Math.min(w, right + pad);
    const out = document.createElement("canvas");
    out.width = right - left; out.height = bottom - top;
    out.getContext("2d").drawImage(canvas, left, top, out.width, out.height, 0, 0, out.width, out.height);
    img.src = out.toDataURL("image/png");
  }

  function image(src, alt, trimmed) {
    return '<a class="asset-preview" href="' + esc(src) + '" target="_blank" rel="noopener"><img alt="' + esc(alt) +
      '" data-src="' + esc(src) + '"' + (trimmed ? ' data-trim="1"' : "") + '></a>';
  }

  function floatCard(item) {
    const build = index.floats.build;
    const placed = build?.floats.find(f => f.key === item.key);
    // The confirm button names exactly what this card shows: a compiled page of one
    // build, or the image file as loaded now. The server records that, not whatever
    // is on disk when the button is pressed.
    let view, seen = {build: "", digest: item.digest};
    if (placed?.page) {
      seen = {build: String(build.build), digest: placed.digest};
      view = image("/api/floats/" + build.build + "/pages/" + placed.page, titleOf(item) + " 所在页面", true) +
        '<p class="muted">第 ' + placed.physical + ' 页' + (build.stale ? " · 编译后源码有改动" : "") + '</p>';
    } else if (item.preview) {
      view = image("/api/assets/" + item.id + "?v=" + encodeURIComponent(item.digest), titleOf(item) + " 的图片文件", /\.pdf$/i.test(item.graphics[0])) +
        '<p class="muted">尚未编译，显示的是图片文件本身</p>';
    } else {
      view = '<pre class="asset-source">' + esc(item.source) + '</pre><p class="muted">尚未编译，显示的是 LaTeX 源码</p>';
    }
    const confirmed = index.floats.confirmed[item.key];
    const pending = index.floats.notes.filter(n => n.target === item.key && n.status === "open").length;
    return '<article class="asset-card float-card"><h3>' + esc(titleOf(item)) + '</h3>' + view +
      (item.caption ? '<p class="asset-caption" translate="no">' + esc(item.caption) + '</p>' : "") +
      '<p class="muted"><span translate="no">' + esc([item.section, item.where].filter(Boolean).join(" · ")) + '</span>' +
      (item.numbered_by === "order" ? " · 按出现顺序编号" : "") + '</p>' +
      '<div class="float-card-actions"><button type="button" class="' + (confirmed ? "primary" : "secondary") +
      '" data-float-confirm="' + esc(item.key) + '" data-float-build="' + esc(seen.build) +
      '" data-float-digest="' + esc(seen.digest) + '" aria-pressed="' + Boolean(confirmed) + '">' +
      (confirmed ? (confirmed.changed ? "已确认 · 之后有改动" : "已确认") : "确认此" + names[item.kind]) + '</button>' +
      '<button type="button" class="quiet" data-float-ask="' + esc(item.key) + '">提调整意见' +
      (pending ? "（" + pending + " 条待处理）" : "") + '</button></div></article>';
  }

  function otherCard(item) {
    if (item.kind === "data") {
      const rows = item.rows.map((row, i) => "<tr>" + row.map(cell => (i ? "<td>" : "<th>") + esc(cell) + (i ? "</td>" : "</th>")).join("") + "</tr>").join("");
      const count = item.total == null ? "" : '<p class="muted">共 ' + item.total + ' 行' +
        (item.total > item.rows.length ? "，显示前 " + item.rows.length + " 行" : "") + '</p>';
      return '<article class="asset-card data"><h3 translate="no">' + esc(item.where) + '</h3><div class="asset-table" translate="no"><table>' + rows +
        '</table></div>' + count + (item.problem ? '<p class="muted">' + esc(item.problem) + '</p>' : "") + '</article>';
    }
    return '<article class="asset-card"><h3 translate="no">' + esc(item.where) + '</h3>' +
      (item.preview ? image("/api/assets/" + item.id, item.where, /\.pdf$/i.test(item.where)) : '<div class="asset-empty">无法预览这类文件</div>') +
      '<p class="muted">项目中的图片文件，论文里还没有使用</p></article>';
  }

  function drawBuild() {
    const build = index.floats.build;
    el("float-build").textContent = build
      ? "第 " + build.build + " 次编译 · " + when(build.created) + " · " + (build.origin === "author" ? "作者触发" : "AI 编译") +
        (build.stale ? " · 之后源码有改动，可重新编译" : "")
      : "还没有编译过图表。AI 写好图表后会编译，也可以现在点「重新编译」。";
    el("float-bar").classList.toggle("stale", Boolean(build?.stale));
    const pdf = el("float-pdf");
    pdf.hidden = !build;
    if (build) pdf.href = "/api/floats/" + build.build + "/pdf";
    el("float-rebuild").disabled = busy || !floatsOf().length;
  }

  function drawNotes() {
    const target = el("float-target"), keep = target.value;
    target.innerHTML = floatsOf().map(item => '<option value="' + esc(item.key) + '">' + esc(titleOf(item)) + '</option>').join("") +
      '<option value="new">新图表</option>';
    if ([...target.options].some(o => o.value === keep)) target.value = keep;
    const notes = index.floats.notes.filter(n => n.status !== "withdrawn").slice().sort((a, b) =>
      (a.status === "open" ? 0 : 1) - (b.status === "open" ? 0 : 1) || b.id - a.id);
    el("float-note-list").innerHTML = notes.map(n => '<li class="float-note ' + n.status + '"><div class="comment-top"><strong>' +
      esc(n.label) + '</strong><span class="note-target">' + (n.status === "open" ? "待 AI 处理" : "已处理 · 第 " + n.answered_build + " 次编译") +
      '</span></div><p translate="no">' + esc(n.text) + '</p>' + (n.response ? '<p class="answer" translate="no"><span class="answer-tag changed">AI</span>' + esc(n.response) + '</p>' : "") +
      (n.status === "open" ? '<button type="button" class="quiet" data-float-withdraw="' + n.id + '">撤回</button>' : "") + '</li>').join("");
  }

  function draw() {
    drawBuild();
    drawNotes();
    const onlySection = el("asset-section").checked && currentTitle();
    tabs.innerHTML = groups.map(([key, label]) => '<label><input type="radio" name="asset-group" value="' + key + '"' +
      (key === active ? " checked" : "") + '>' + label + ' <span class="count">' + index[key].length + '</span></label>').join("");
    let items = index[active];
    if (onlySection && (active === "figures" || active === "tables"))
      items = items.filter(item => (item.section || "").toLowerCase() === currentTitle().toLowerCase());
    const card = active === "figures" || active === "tables" ? floatCard : otherCard;
    grid.innerHTML = items.length ? items.map(card).join("") :
      '<p class="empty">' + (onlySection ? "本节没有这一类内容。" : "这一类还没有内容。") + '</p>';
    for (const img of grid.querySelectorAll("img[data-src]")) {
      img.addEventListener("load", () => { if (img.dataset.trim) trim(img); });
      img.addEventListener("error", () => img.closest(".asset-preview").replaceWith(Object.assign(
        document.createElement("div"), {className: "asset-empty", textContent: "无法预览"})), {once: true});
      img.loading = "lazy";
      img.src = img.dataset.src;
    }
  }

  async function post(body, pending) {
    if (busy) return;
    busy = true; drawBuild(); status(pending);
    try {
      const response = await fetch("/api/workspace", {method: "POST", body: JSON.stringify(body),
        headers: {"Content-Type": "application/json", "X-Paperroom-Token": window.roomToken}});
      const result = await response.json();
      if (!response.ok) throw Error(result.error || "提交失败。");
      index = result; status("");
      return true;
    } catch (error) {
      status(error.message, true);
      return false;
    } finally {
      busy = false;
      if (index) draw();
    }
  }

  el("open-assets").addEventListener("click", async () => {
    const mine = ++visit;
    if (!dialog.open) dialog.showModal();
    const title = currentTitle();
    el("asset-section-label").hidden = !title;
    el("asset-section").checked = Boolean(title);
    grid.innerHTML = ""; tabs.innerHTML = "";
    status("正在读取论文中的图表…");
    try {
      const response = await fetch("/api/assets", {cache: "no-store"});
      const result = await response.json();
      if (!response.ok) throw Error(result.error || "读取失败。");
      if (mine !== visit || !dialog.open) return;
      index = result;
      el("assets-source").textContent = result.main ? "来自 " + result.main + " 和项目文件夹" : "来自项目文件夹";
      status(result.problem || "");
      if (!index[active].length) active = groups.find(([key]) => index[key].length)?.[0] || "figures";
      draw();
    } catch (error) {
      if (mine === visit) status("读取失败。 " + error.message, true);
    }
  });
  el("close-assets").addEventListener("click", () => dialog.close());
  el("float-rebuild").addEventListener("click", () =>
    post({action: "float_build"}, "正在编译整篇论文，可能需要一点时间…"));
  el("float-note-form").addEventListener("submit", async e => {
    e.preventDefault();
    const text = el("float-text").value.trim();
    if (!text) { status("请写下希望怎样调整。", true); return; }
    if (await post({action: "float_note", target: el("float-target").value, text}, "正在保存指令…")) {
      el("float-text").value = "";
      status("已保存。回到原对话发一条消息，AI 就会看到并处理。");
    }
  });
  dialog.addEventListener("click", e => {
    const confirm = e.target.closest("[data-float-confirm]");
    if (confirm) return post({action: "float_confirm", target: confirm.dataset.floatConfirm,
      confirmed: confirm.getAttribute("aria-pressed") !== "true",
      build: confirm.dataset.floatBuild ? Number(confirm.dataset.floatBuild) : null,
      digest: confirm.dataset.floatDigest}, "");
    const ask = e.target.closest("[data-float-ask]");
    if (ask) {
      el("float-target").value = ask.dataset.floatAsk;
      el("float-text").focus();
      el("float-text").scrollIntoView({block: "center"});
      return;
    }
    const withdraw = e.target.closest("[data-float-withdraw]");
    if (withdraw) post({action: "float_withdraw", id: Number(withdraw.dataset.floatWithdraw)}, "");
  });
  dialog.addEventListener("change", e => {
    if (e.target.name === "asset-group") active = e.target.value;
    if (index && (e.target.name === "asset-group" || e.target.id === "asset-section")) draw();
  });
})();
