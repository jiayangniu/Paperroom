// Extract each physical page separately so PDFKit and Poppler use the same page order.
ObjC.import("PDFKit");
function run(args) {
  const pdf = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(args[0]));
  const pages = [];
  for (let i = 0; i < Number(pdf.pageCount); i++) {
    pages.push(ObjC.unwrap(pdf.pageAtIndex(i).string) || "");
  }
  return JSON.stringify(pages);
}
