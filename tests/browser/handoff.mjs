import assert from "node:assert/strict";
import {launch} from "./cdp.mjs";

const [chrome, base, mode, section, port] = process.argv.slice(2);
const page = await launch(chrome, Number(port));
try {
  await page.goto(base + "view=section&section=" + section);
  const role = 'textarea[data-field="purpose"]';
  await page.waitFor("document.querySelector(" + JSON.stringify(role) + ")");
  if (mode === "write") {
    await page.click(role);
    await page.type("unsent outline");
    await page.waitFor("el('draft-hint').textContent.includes('草稿已保存在此项目')");
    await page.goto(base + "view=review&section=" + section);
    await page.waitFor("el('note-body')");
    await page.click("#page-1 img");
    await page.click("#note-body");
    await page.type("unsent review");
    await page.waitFor("el('draft-hint').textContent.includes('草稿已保存在此项目')");
  } else {
    assert.match(await page.eval("return document.querySelector(" + JSON.stringify(role) + ").value"), /unsent outline/);
    await page.goto(base + "view=review&revision=0");
    await page.waitFor("el('version-choice')");
    assert.equal(await page.eval("return el('note-body')"), null);
    await page.eval("el('version-choice').value='1';el('version-choice').dispatchEvent(new Event('change',{bubbles:true}))");
    await page.waitFor("el('note-body')?.value==='unsent review'");
    assert.equal(await page.eval("return model.fields.entry.page"), 1);
    assert.equal(await page.eval("return Boolean(model.fields.entry.pin)"), true);
    await page.click('[data-op="submit-review"]');
    await page.waitFor("el('notice').textContent.includes('已提交')");
  }
} finally {
  page.close();
}
