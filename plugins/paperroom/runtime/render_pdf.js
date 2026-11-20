// macOS ships PDFKit and the JavaScript for Automation runtime.
ObjC.import("PDFKit");
ObjC.import("AppKit");
function run(args) {
  const [filename, directory, selection, limit, output] = args;
  const document = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(filename));
  const total = Number(document.pageCount);
  if (!total) throw Error("无法打开 PDF。");
  if (selection === "geometry") {
    const page = document.pageAtIndex(0);
    const size = page.boundsForBox(1).size;
    const rotated = Number(page.rotation) % 180 !== 0;
    return JSON.stringify({pages:total, ratio:rotated ? size.width/size.height : size.height/size.width});
  }
  if (selection === "all" && Number(limit) > 0 && total > Number(limit))
    throw Error("请指定本节页码，一次最多保存 " + limit + " 页。");
  const excerpt = output ? $.PDFDocument.alloc.init : null;
  const pages = selection === "all" ? Array.from({length:total}, (_, i) => i + 1)
                                     : selection.split(",").map(Number);
  pages.forEach((n, index) => {
    if (!Number.isInteger(n) || n < 1 || n > total) throw Error("页码超出范围：" + n);
    const page = document.pageAtIndex(n - 1);
    if (excerpt) excerpt.insertPageAtIndex(page.copy, index);
    const size = page.boundsForBox(1).size;
    const scale = Number(limit) > 0 ? Math.min(2, 2400 / Math.max(size.width, size.height)) : 2;
    const image = page.thumbnailOfSizeForBox($.NSMakeSize(size.width * scale, size.height * scale), 1);
    const bitmap = $.NSBitmapImageRep.imageRepWithData(image.TIFFRepresentation);
    const png = bitmap.representationUsingTypeProperties(4, $({}));
    const path = directory + "/page-" + (index + 1) + ".png";
    if (!png.writeToFileAtomically(path, true)) throw Error("无法写入 " + path);
  });
  if (excerpt && !excerpt.writeToURL($.NSURL.fileURLWithPath(output)))
    throw Error("无法保存 PDF 节选。");
}
