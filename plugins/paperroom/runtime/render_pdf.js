// macOS ships PDFKit and the JavaScript for Automation runtime.
ObjC.import("PDFKit");
ObjC.import("AppKit");
function run(args) {
  const [filename, directory, selection] = args;
  const document = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(filename));
  const total = Number(document.pageCount);
  if (!total) throw Error("无法打开 PDF。");
  const pages = selection === "all" ? Array.from({length:total}, (_, i) => i + 1)
                                     : selection.split(",").map(Number);
  pages.forEach((n, index) => {
    if (!Number.isInteger(n) || n < 1 || n > total) throw Error("页码超出范围：" + n);
    const page = document.pageAtIndex(n - 1);
    const size = page.boundsForBox(1).size;
    const image = page.thumbnailOfSizeForBox($.NSMakeSize(size.width * 2, size.height * 2), 1);
    const bitmap = $.NSBitmapImageRep.imageRepWithData(image.TIFFRepresentation);
    const png = bitmap.representationUsingTypeProperties(4, $({}));
    const path = directory + "/page-" + (index + 1) + ".png";
    if (!png.writeToFileAtomically(path, true)) throw Error("无法写入 " + path);
  });
}
