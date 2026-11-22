/* Exercise the author's cleanup and previously shared URLs against the workspace HTTP server. */
import assert from "node:assert/strict";
import {launch} from "./cdp.mjs";

const [chrome, base, step, port] = process.argv.slice(2);
const page = await launch(chrome, Number(port));

async function openReader() {
  await page.goto(base + "view=review");
  await page.waitFor("document.querySelector('#open-document-reader')?.offsetWidth");
  await page.click("#open-document-reader");
  await page.waitFor("document.querySelector('.reader-pane .version-tag')?.offsetWidth");
}
async function currentPair() {
  return page.eval("return [...document.querySelectorAll('.reader-pane')].map(p => [p.dataset.doc, p.querySelector('.version-tag').textContent])");
}
function httpStatus(path) {
  return page.eval("return (await fetch(" + JSON.stringify(path) + ", {cache: 'no-store'})).status");
}
async function showPreview() {
  await page.click("#manage-versions");
  assert(await page.eval("return document.querySelector('[data-clean-version=\"0\"]').disabled"));
  for (const id of [1, 2, 3]) await page.click('[data-clean-version="' + id + '"]');
  await page.click("#preview-cleanup");
  await page.waitFor("document.querySelector('#confirm-cleanup')?.offsetWidth");
  const rows = await page.eval("return [...document.querySelectorAll('#cleanup-body li')].map(row => row.textContent.replace(/\\s/g, ''))");
  assert.deepEqual(rows, ["V0·原稿→V0", "V1·Run1→清理PDF批注1", "V2·Run2→清理PDF批注0",
                          "V3·Run3→清理PDF批注0", "V4·Run4→V1"]);
}

try {
  await page.viewport(1440, 960);
  await openReader();
  if (step === "cleanup") {
    assert.deepEqual(await currentPair(), [["v-3", "V3"], ["v-4", "V4"]]);
    await showPreview();
    await page.click("#cancel-cleanup");
    assert.equal(await httpStatus("/api/versions/1/pdf"), 200);
    // Reopen from the regular entry point as an author who came back after cancelling.
    await openReader();
    await showPreview();
    await page.click("#confirm-cleanup");
    await page.waitFor("document.querySelector('.reader-pane[data-doc=\"v-4\"] .version-tag')?.textContent === 'V1'");
    assert.deepEqual(await currentPair(), [["v-0", "V0"], ["v-4", "V1"]]);
    for (const id of [1, 2, 3]) {
      assert.equal(await httpStatus("/api/versions/" + id + "/pdf"), 410);
      assert.equal(await httpStatus("/api/versions/" + id + "/pages/1"), 410);
    }
    assert.equal(await httpStatus("/api/versions/4/pdf"), 200);
    await page.goto(base + "view=review&panel=versions&before=1&after=4&mode=compare");
    await page.waitFor("document.querySelector('#document-reader')?.innerText.includes('已清理')");
  } else {
    assert.equal(step, "next-version");
    assert.deepEqual(await currentPair(), [["v-4", "V1"], ["v-5", "V2"]]);
  }

  // Review links circulated before cleanup must always refer to the same review.
  await page.goto(base + "view=review&revision=1");
  await page.waitFor("document.body.innerText.includes('已清理') && document.body.innerText.includes('Note on Run 1.')");
  assert.equal(await page.eval("return !!document.querySelector('img[src^=\"/api/versions/4/\"]')"), false);
  await page.goto(base + "view=review&revision=4");
  await page.waitFor("document.querySelector('.manuscript .page-bar h3')?.textContent === 'V1 · Run 4'");
  assert(await page.eval("return document.body.innerText.includes('Note on Run 4.')"));
} finally {
  page.close();
}
