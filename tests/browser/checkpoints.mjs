/* Returning to a saved copy must also let the author recover their outgoing work. */
import assert from "node:assert/strict";
import {existsSync, readFileSync, writeFileSync} from "node:fs";
import {join} from "node:path";
import {launch} from "./cdp.mjs";

const [chrome, base, project, section, port] = process.argv.slice(2);
const page = await launch(chrome, Number(port));
const field = 'textarea[data-field="purpose"]';
const manuscript = join(project, "main.tex");
const appendix = join(project, "appendix.tex");

async function showSnapshots() {
  await page.waitFor("document.querySelector('#open-checkpoints')?.offsetWidth");
  await page.click("#open-checkpoints");
  await page.waitFor("document.querySelector('#save-checkpoint')?.offsetWidth && " +
                     "document.querySelector('#checkpoint-controls')?.disabled === false");
}

async function switchTo(id, outgoingCommit) {
  await showSnapshots();
  await page.click('[data-checkpoint-id="' + id + '"]');
  await page.waitFor("document.querySelector('#switch-checkpoint')?.offsetWidth");
  if (outgoingCommit) {
    await page.click("#checkpoint-commit");
    await page.type(outgoingCommit);
  }
  await page.click("#switch-checkpoint");
  // A restore deliberately lands on the project root, since old section IDs may no longer exist.
  await page.waitFor("document.querySelector('#nav [data-view=paper][aria-current=page]')?.offsetWidth");
  await page.click('#nav [data-view="section"][data-section="' + section + '"]');
}

try {
  await page.viewport(1280, 900);
  await page.goto(base + "view=section&section=" + section);
  await page.waitFor("document.querySelector(" + JSON.stringify(field) + ")?.offsetWidth");
  const original = await page.eval("return document.querySelector(" + JSON.stringify(field) + ").value");
  await showSnapshots();
  await page.click("#checkpoint-commit");
  await page.type("Outline A");
  await page.click("#save-checkpoint");
  await page.waitFor("document.querySelector('#checkpoint-list')?.textContent.includes('Outline A')");
  const idA = await page.eval("return document.querySelector('#checkpoint-list [data-checkpoint-id]').dataset.checkpointId");
  await page.click("#close-checkpoints");

  writeFileSync(manuscript, "Manuscript B\n");
  writeFileSync(appendix, "B-only appendix\n");
  await page.click(field);
  await page.type("unsubmitted idea B");
  // Switch immediately, while the outline draft may still be waiting to sync.
  await switchTo(idA, "Newer manuscript B");
  await page.waitFor("document.querySelector(" + JSON.stringify(field) + ")?.value === " + JSON.stringify(original));
  assert.equal(readFileSync(manuscript, "utf8"), "Manuscript A\n");
  assert.equal(existsSync(appendix), false);

  await showSnapshots();
  await page.waitFor("document.querySelector('#checkpoint-list')?.textContent.includes('Newer manuscript B')");
  const idB = await page.eval("return [...document.querySelectorAll('#checkpoint-list [data-checkpoint-id]')]" +
                              ".map(row=>row.dataset.checkpointId).find(id=>id!==" + JSON.stringify(idA) + ")");
  assert.ok(idB);
  await page.click("#close-checkpoints");
  await switchTo(idB, "");
  await page.waitFor("document.querySelector(" + JSON.stringify(field) + ")?.value.includes('unsubmitted idea B')");
  assert.equal(readFileSync(manuscript, "utf8"), "Manuscript B\n");
  assert.equal(readFileSync(appendix, "utf8"), "B-only appendix\n");
} finally {
  page.close();
}
