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
  let generation = 0, spots = new Map(), arrived = null, quiet = null, jumps = new Map();
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
  function documentLabel(doc) {
    return [versionName(doc), localDate(created(doc))].filter(Boolean).join(" · ");
  }
  function detail(doc) {
    return [localDate(created(doc)), doc.pages + " 页"].filter(Boolean).join(" · ");
  }
  function tag(doc) { return "V" + doc.number; }
  function sideOf(doc, side) {
    if (side === "before" || side === "after") return side;
    return doc.id === after ? "after" : doc.id === before ? "before" : "";
  }

  function latest(doc) {
    return documents.length > 1 && !documents.some(item => item.number > doc.number);
  }
  function pane(doc, side) {
    const caption = tag(doc);
    const name = versionName(doc);
    const version = sideOf(doc, side);
    const options = documents.map(item => '<option value="'+esc(item.id)+'"'+(item.id===doc.id?' selected':'')+'>'+
      esc(documentLabel(item))+'</option>').join("");
    const swappable = documents.length > 1;
    const swap = swappable ? '<label class="reader-swap"><span>换一份</span><select data-reader-side="'+side+
      '" aria-label="更换这一侧显示的版本" translate="no">'+options+'</select></label>' : "";
    const pdf = doc.pdf_url
      ? '<a href="'+esc(doc.pdf_url)+'" target="_blank" rel="noopener">打开 PDF</a>'
      : '<small>旧版仅存页图</small>';
    const pages = Array.from({length:doc.pages}, (_, i) => '<figure><figcaption>'+esc(caption)+' · 第 '+(i+1)+' / '+
      doc.pages+' 页</figcaption><img src="'+esc(doc.page_url)+String(i+1)+'" alt="'+esc(caption)+' · 第 '+(i+1)+
      ' 页"></figure>').join("");
    return '<section class="reader-pane" data-pane="'+side+'" data-version="'+version+'" data-doc="'+esc(doc.id)+'"><header class="reader-pane-head">'+
      '<span class="version-tag '+version+'">'+esc(caption)+'</span>'+
      '<span class="version-name"><strong translate="no">'+esc(name)+'</strong><small>'+(latest(doc)?'<span class="latest-badge">最新</span>':'')+esc(detail(doc))+'</small></span>'+
      '<span class="reader-tail"><span class="page-count" aria-hidden="true">共 '+doc.pages+' 页</span>'+pdf+'</span>'+swap+
      '</header><div class="reader-pages" role="region" aria-label="'+esc(caption)+'" tabindex="0">'+pages+'</div></section>';
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
  /* Opened from the outline: start the page with that section or paragraph at the top. */
  async function jumpTo(box, index) {
    if (!box) return;
    const list = [...figures(box)];
    const target = list[Math.min(index, list.length - 1)];
    if (!target) return;
    await pagesReady(list, index);
    quiet = box;
    box.scrollTop += target.getBoundingClientRect().top - box.getBoundingClientRect().top - 6;
    requestAnimationFrame(() => { if (quiet === box) quiet = null; });
    jumps.delete(box.closest(".reader-pane")?.dataset.doc);
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
    const pair = flippable();
    if (!comparing && pair) showing = single === before ? "before" : "after";
    flipBar.hidden = !pair;
    flipBar.classList.toggle("single", !comparing);
    flipBar.innerHTML = pair ? ["before","after"].map(side => '<button type="button" data-flip="'+side+'" aria-pressed="'+
      (showing===side)+'"><b>'+(side==="before"?"较早":"较新")+'</b><span translate="no">'+esc(versionName(byId(side==="before"?before:after)))+
      '</span></button>').join("") : "";
    el("reader-sync-label").hidden = !comparing;
    el("reader-sync").checked = syncScroll;
    for (const input of reader.querySelectorAll('input[name="reader-zoom"]')) input.checked = Number(input.value) === zoom;
    el("reader-title").textContent = comparing ? "版本对照" : "排版版本";
    el("reader-alone").textContent = aloneMessage();
    el("reader-alone").hidden = !aloneMessage();
  }
  function flippable() { return Boolean(byId(before) && byId(after) && (!comparing || narrow.matches)); }
  function aloneMessage() {
    if (documents.length !== 1) return "";
    return "目前只有这一个版本。以后在原对话里让 AI 保存新版本，就能在这里对照。";
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
      await Promise.all(sides().map(side => jumps.has(paneDoc(side))
        ? jumpTo(scroller(side), jumps.get(paneDoc(side))) : place(scroller(side), spots.get(paneDoc(side)))));
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
    if (!flippable() || side === showing) return;
    if (!comparing) {
      // One version at a time: the other version opens at the same reading spot.
      const now = spotOf(scroller("only")), target = side === "before" ? before : after;
      if (now) spots.set(target, anchorSpot(single, target, now));
      single = target; showing = side;
      pinComparison();
      await draw();
      flipBar.querySelector('[data-flip="'+side+'"]')?.focus({preventScroll:true});
      return;
    }
    const from = scroller(showing), now = spotOf(from);
    const stayed = arrived?.side === showing && spotDistance(arrived.spot, now) < 0.03;
    if (now) spots.set(paneDoc(showing), now);
    showing = side;
    paint();
    const target = scroller(side);
    // Visiting the other version without scrolling returns exactly where it was;
    // after reading on, the other version follows to the matching spot.
    if (!stayed || !spots.get(paneDoc(side))) await place(target, anchorSpot(paneDoc(side === "before" ? "after" : "before"), paneDoc(side), now));
    arrived = {side, spot: spotOf(target)};
    updateCounts();
    flipBar.querySelector('[data-flip="'+side+'"]')?.focus({preventScroll:true});
  }

  function setPair(pair, items, mode) {
    documents = items;
    before = pair.before?.id || "";
    after = pair.after?.id || "";
    single = after;
    comparing = Boolean(before && after) && mode !== "latest";
  }
  /* Versions shift text between pages. Carry a reading spot to the other version by the
     last section or paragraph that starts at or before it, keeping the distance from it. */
  function anchorSpot(fromId, toId, spot) {
    const from = byId(fromId), to = byId(toId);
    if (!spot || !from?.map || !to?.map || fromId === toId) return spot;
    const page = spot.page + 1;
    let best = null;
    for (const [sid, place] of Object.entries(from.map)) {
      const marks = [[sid, null, place.page], ...Object.entries(place.paragraphs || {}).map(([pid, pg]) => [sid, pid, pg])];
      for (const [s, p, pg] of marks) if (pg && pg <= page && (!best || pg >= best.page)) best = {s, p, page: pg};
    }
    if (!best) return spot;
    const target = best.p ? to.map[best.s]?.paragraphs?.[best.p] : to.map[best.s]?.page;
    return target ? {page: target - 1 + page - best.page, f: spot.f} : spot;
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

  function openReader(selection={}) {
    section="versions";
    ++generation;
    el("reader-section").textContent="";
    const items=versionDocs();
    const pair=items.length?readerPair(items,selection):null;
    if (!pair) {
      if (!reader.open) reader.showModal();
      panels.replaceChildren();
      reader.querySelector(".reader-tools").hidden=true;
      el("reader-alone").hidden=true; showImport(false);
      message(items.length?"所选版本不存在。":"还没有排版版本。觉得某一版值得留下时，在原对话里说「把这一版放进 Paperroom」。",Boolean(items.length));
      return false;
    }
    reader.querySelector(".reader-tools").hidden=false;
    setPair(pair, items, selection.mode);
    showing="after"; zoom=narrow.matches?1.3:1; spots=new Map(); jumps=new Map(); arrived=null; drawn="";
    const saved=memory.get(section);
    if (route.section) {
      // Opened from the outline: every version starts at that section or paragraph's page.
      for (const doc of items) jumps.set(doc.id, anchorPage(doc, route.section, route.paragraph) - 1);
      if (saved) zoom = saved.zoom;
    } else if (selection.before == null && !selection.mode && saved && saved.pair===before+"|"+after) {
      ({comparing, showing, zoom} = saved);
      single=saved.single; spots=new Map(saved.spots);
    }
    form.reset(); selectSource(); el("reader-fields").disabled=false;
    el("toggle-import").hidden=true;
    showImport(false);
    message();
    if (!reader.open) reader.showModal();
    draw();
    return true;
  }

  function pinComparison(){
    setPanelRoute("versions",{before:byId(before)?.number,after:byId(after)?.number,mode:comparing?"compare":"latest"});
  }
  window.openPaperroomComparison=openReader;
  document.addEventListener("focusin", e => {
    if (e.target.closest?.("#note-editor, #author-form")) lastField = e.target;
  });
  document.addEventListener("click", async e=>{
    if (!e.target.closest("#open-document-reader")) return;
    const requestedSection=route.section, navigation=loadId, request=++generation;
    try {
      // A new version can arrive while an unsent review keeps the editor on its
      // old snapshot. Refresh only the version list before choosing the pair.
      const fresh=await fetchData(dataUrl());
      if (request!==generation || navigation!==loadId || route.section!==requestedSection) return;
      data.versions=arr(fresh.versions);
      if (openReader()) pinComparison();
    } catch (err) {
      if (request===generation && navigation===loadId) notice(err.message,true);
    }
  });
  el("close-reader").addEventListener("click",()=>reader.close());
  reader.addEventListener("close",()=>{
    clearPanelRoute("versions");
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
    if (!flippable() || e.target.matches("input,select,textarea") || e.altKey || e.metaKey || e.ctrlKey) return;
    // Enlarged pages keep the arrows for sideways scrolling.
    const box = e.target.closest?.(".reader-pages");
    if (box && box.scrollWidth > box.clientWidth + 1) return;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      flip(e.key === "ArrowLeft" ? "before" : "after");
    }
  });
  reader.addEventListener("change", async e=>{
    if (e.target.name==="reader-mode") {
      saveSpots();
      comparing=e.target.value==="compare" && documents.length>1;
      if (!comparing) single = showing==="before"&&byId(before) ? before : after||single;
      pinComparison();
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
    saveSpots();
    if (side==="only") single=e.target.value;
    else {
      const other=side==="before"?after:before;
      if (e.target.value===other) { if (side==="before") after=before; else before=after; }
      if (side==="before") before=e.target.value; else after=e.target.value;
      // Keep the earlier version on the left.
      if ((byId(before)?.number ?? 0) > (byId(after)?.number ?? 0)) [before, after]=[after, before];
    }
    pinComparison();
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
      const side = box.closest(".reader-pane").dataset.pane, otherSide = side === "before" ? "after" : "before";
      const other = scroller(otherSide);
      const spot = anchorSpot(paneDoc(side), paneDoc(otherSide), spotOf(box));
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
      setPair({before:null,after:newRef});
      await draw(); pinComparison();
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
    paper_hint: "AI 给出了整篇大纲参考",
    paper_polish_adopted: "AI 已按作者要求润色章节安排",
    paragraph_polish_adopted: "AI 已按作者要求润色逐句意图",
    section_hint: "AI 给出了段落安排参考",
    sentence_reference: "AI 给出了逐句参考",
    section_outline: "章节段落大纲已提交",
    section_polish_proposed: "AI 提出了段落大纲润色建议",
    section_polish_adopted: "作者采纳了段落大纲润色",
    paragraph_outline: "段内逐句大纲已提交",
    section_published: "整节成稿已发布",
    section_reviewed: "整节审阅已提交",
    version_saved: "排版版本已保存",
    version_reviewed: "版本审阅已提交"
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

/* Prepared files are read-only. A legacy build link always reads its archived pages. */
(() => {
  "use strict";
  const dialog = el("asset-browser");
  const tabs = el("asset-tabs");
  const picker = el("asset-file");
  const preview = el("asset-preview");
  const refresh = el("asset-refresh");
  const directory = el("asset-directory");
  let index, build, section, group = "figures", request = 0;
  let selected = {};

  function status(message, error = false) {
    el("assets-status").textContent = message;
    el("assets-status").classList.toggle("error", error);
  }

  function files() {
    const items = index[group] || [];
    return build && section ? items.filter(item => item.section === section.title) : items;
  }

  function fileName(item) {
    if (build) {
      const kind = group === "figures" ? tr("图") : tr("表");
      return kind + " " + item.number + (item.label ? " · " + item.label : "");
    }
    const prefix = index.directories[group] + "/";
    return item.path.startsWith(prefix) ? item.path.slice(prefix.length) : item.name;
  }

  function showPreview() {
    const item = files().find(file => (build ? file.key : file.id) === picker.value);
    const link = el("asset-original"), digest = el("asset-digest");
    preview.replaceChildren();
    link.hidden = digest.hidden = !item;
    if (!item) {
      status("所选文件已移出此目录。");
      return;
    }
    status("");
    selected[group] = picker.value;
    const url = build ? "/api/floats/" + build + "/pdf" : item.preview_url;
    link.href = url;
    link.textContent = build || item.kind === "pdf" ? "打开 PDF" : "打开原文件";
    digest.textContent = build ? "" : "SHA-256 " + item.digest.slice(0, 12);
    digest.title = build ? "" : item.digest;
    if (!build && item.kind === "pdf") {
      // A single page opens without the viewer's sidebar and toolbar, fitted to the
      // width with the frame cut to the page; multi-page PDFs keep paging and zoom.
      const frame = document.createElement("iframe");
      frame.setAttribute("translate", "no");
      frame.title = item.name;
      preview.append(frame);
      const shown = picker.value;
      const open = layout => {
        if (!frame.isConnected || picker.value !== shown) return;
        const single = layout?.pages === 1 && layout.ratio > 0;
        if (single) {
          frame.style.setProperty("--page-height-ratio", String(layout.ratio));
          frame.classList.add("sized-pdf");
        } else frame.classList.add("paged-pdf");
        frame.src = url + "#view=FitH&navpanes=0" + (single ? "&toolbar=0&scrollbar=0" : "");
      };
      fetch(url + "&layout=1").then(response => response.ok ? response.json() : null)
        .then(open, () => open(null));
    } else if (!build || item.page) {
      const img = document.createElement("img");
      img.setAttribute("translate", "no");
      img.alt = fileName(item);
      img.addEventListener("error", () => {
        if (preview.contains(img)) status("预览不可用，请刷新列表。", true);
      }, {once: true});
      img.src = build ? "/api/floats/" + build + "/pages/" + item.page : url;
      preview.append(img);
    } else {
      preview.textContent = "此版本没有保存页面预览。";
    }
    if (build && item.caption) {
      const caption = document.createElement("p");
      caption.setAttribute("translate", "no");
      caption.textContent = item.caption;
      preview.append(caption);
    }
  }

  function drawGroup() {
    tabs.querySelector('input[value="' + group + '"]').checked = true;
    directory.textContent = build ? section?.title || "" : index.directories[group] + "/";
    directory.hidden = !directory.textContent;
    const items = files();
    picker.replaceChildren();
    preview.replaceChildren();
    el("asset-view").hidden = !items.length;
    if (!items.length) {
      if (build) status("这一类还没有内容。");
      else if (group === "tables") status("此目录暂无表格 PDF。请在聊天中让 AI 将 LaTeX 表格编译为 PDF，保存到上面的目录后刷新。");
      else status("此目录暂无文件。请在对话中让 AI 将准备好的文件保存到上面的目录，再刷新列表。");
      return;
    }
    for (const item of items) {
      const option = new Option(fileName(item), build ? item.key : item.id);
      option.setAttribute("translate", "no");
      picker.add(option);
    }
    if (selected[group]) {
      if (![...picker.options].some(option => option.value === selected[group])) {
        const missing = new Option(tr("选择文件"), "");
        missing.disabled = true;
        picker.add(missing, 0);
        picker.value = "";
      } else {
        picker.value = selected[group];
      }
    }
    showPreview();
  }

  async function load(number, chooseFirst = false) {
    const mine = ++request;
    if (number !== build) selected = {};
    build = number;
    index = null;
    setPanelRoute("figures", {section: build && section ? section.id : null, build});
    el("asset-archive").hidden = !build;
    el("asset-build").textContent = build ? tr("第 " + build + " 次编译") : "";
    tabs.disabled = refresh.disabled = true;
    directory.hidden = el("asset-view").hidden = true;
    preview.replaceChildren();
    status("正在读取图表…");
    try {
      const url = build ? "/api/assets?build=" + encode(build) : "/api/prepared-assets";
      const response = await fetch(url, {cache: "no-store"});
      const result = await response.json();
      if (mine !== request || !dialog.open) return;
      if (!response.ok) throw Error(result.error || "读取失败。");
      if (build && result.floats?.build?.build !== build) throw Error("找不到指定的图表编译版本。");
      index = result;
      tabs.disabled = false;
      if (chooseFirst && !files().length) {
        group = "tables";
        if (!files().length) group = "figures";
      }
      drawGroup();
    } catch (error) {
      if (mine === request) status(error.message, true);
    } finally {
      if (mine === request) refresh.disabled = false;
    }
  }

  function openAssets(options = {}) {
    if (!dialog.open) dialog.showModal();
    const sections = [...arr(data?.outline?.sections), ...arr(data?.archived)];
    section = options.build && sections.find(s => s.id === options.section);
    group = "figures";
    selected = {};
    return load(options.build || null, true);
  }

  window.openPaperroomAssets = openAssets;
  el("open-assets").addEventListener("click", () => openAssets());
  document.addEventListener("click", event => {
    if (event.target.closest?.("#open-section-assets")) openAssets();
  });
  el("asset-current").addEventListener("click", () => openAssets());
  tabs.addEventListener("change", event => {
    group = event.target.value;
    drawGroup();
  });
  picker.addEventListener("change", showPreview);
  refresh.addEventListener("click", () => load(build));
  el("close-assets").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => {
    if (!dialog.open) {
      ++request;
      preview.replaceChildren();
    }
    clearPanelRoute("figures");
  });
})();


if (window.CSS && !window.CSS.supports("field-sizing","content")) {
  const desktop = matchMedia("(min-width:721px)");
  const fields = '#plan-rows:is([data-level="paper"],[data-level="section"],[data-level="paragraph"]) textarea';
  const resize = field => {
    field.style.height = "";
    if (desktop.matches) field.style.height = (field.scrollHeight + field.offsetHeight - field.clientHeight) + "px";
  };
  const resizeAll = () => document.querySelectorAll(fields).forEach(resize);
  new MutationObserver(resizeAll).observe(el("content"), {childList:true,subtree:true});
  document.addEventListener("input", e => { if (e.target.matches(fields)) resize(e.target); });
  window.addEventListener("resize",resizeAll);
  resizeAll();
}

/* The writing reference column fits the window from wherever it starts, so the
   folded headings at its foot stay in view before the page is scrolled. */
if (window.MutationObserver) (() => {
  let frame = 0;
  const fit = () => {
    frame = 0;
    const sheet = document.querySelector(".plan-reference");
    if (!sheet) return;
    const top = Math.max(16, sheet.getBoundingClientRect().top);
    sheet.style.setProperty("--reference-room", Math.max(260, Math.round(innerHeight - top - 16)) + "px");
  };
  const soon = () => { if (!frame) frame = requestAnimationFrame(fit); };
  addEventListener("scroll", soon, {passive:true});
  addEventListener("resize", soon);
  new MutationObserver(soon).observe(el("content"), {childList:true});
  fit();
})();

/* Opening a folded heading brings its material into view; closing it returns the
   sentence reference to where the author was reading. */
if (window.MutationObserver) (() => {
  let kept = 0;
  // Read the spot before the fold opens: once open, the reference stops scrolling on its own.
  document.addEventListener("click", e => {
    const fold = e.target.closest?.(".plan-reference .context-fold>summary")?.parentElement;
    const slot = el("sentence-reference-slot");
    if (fold && !fold.open && slot && !fold.closest(".reference-body").querySelector(".context-fold[open]"))
      kept = slot.scrollTop;
  }, true);
  document.addEventListener("toggle", e => {
    const fold = e.target;
    if (!fold.matches?.(".plan-reference .context-fold")) return;
    const body = fold.closest(".reference-body"), slot = el("sentence-reference-slot");
    if (fold.open) {
      requestAnimationFrame(() => {
        // The section plan opens at the paragraph being written, with its neighbours around it.
        const here = fold.querySelector("li.here");
        const target = here || fold, lead = here ? Math.min(140, body.clientHeight / 4) : 8;
        body.scrollTop += target.getBoundingClientRect().top - body.getBoundingClientRect().top - lead;
      });
    } else if (slot && !body.querySelector(".context-fold[open]")) {
      requestAnimationFrame(() => { slot.scrollTop = kept; });
    }
  }, true);
})();
