"""Exercise the browser event handlers shared by the current and offline author rooms."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAGES = ["plugins/paperroom/runtime/workspace.html", "plugins/paperroom/runtime/room.html",
         "demo/room.html", "demo/demo.html"]


def guard(page):
    html = (ROOT / page).read_text(encoding="utf-8")
    return re.search(r'<script id="author-clipboard">(.*?)</script>', html, re.DOTALL).group(1)


class ClipboardTests(unittest.TestCase):
    def test_standalone_pages_ship_the_same_event_policy(self):
        for page in PAGES[1:]:
            with self.subTest(page=page):
                self.assertEqual(guard(page), guard(PAGES[0]))

    @unittest.skipUnless(shutil.which("node"), "Clipboard event dispatch requires Node.js")
    def test_rejects_transfers_only_during_author_entry(self):
        harness = """
const assert = require('node:assert/strict');
const document = new EventTarget();
document.body = {dataset: {}};
let activeRoom = true;
const notice = {textContent: ''};
document.querySelector = () => activeRoom;
document.getElementById = () => notice;
let inDialog = false;
let authorField = true;
document.closest = selector => selector === 'dialog' ? inDialog : authorField;
"""
        checks = """
function blocked(type, inputType = '') {
    const event = new Event(type, {cancelable: true});
    event.inputType = inputType;
    document.dispatchEvent(event);
    return event.defaultPrevented;
}
for (const type of ['copy', 'cut', 'paste', 'drop']) assert.equal(blocked(type), true);
for (const input of ['insertFromPaste', 'insertFromPasteAsQuotation', 'insertFromDrop',
                     'insertFromYank', 'deleteByCut', 'deleteByDrag'])
    assert.equal(blocked('beforeinput', input), true, input);
assert.match(notice.textContent, /直接输入/);
for (const input of ['insertText', 'insertCompositionText', 'insertFromComposition',
                     'insertLineBreak', 'historyUndo', 'deleteContentBackward'])
    assert.equal(blocked('beforeinput', input), false, input);
authorField = false;
assert.equal(blocked('copy'), true);                // Reference text in the room.
assert.equal(blocked('selectionchange'), false);    // Select a source sentence for a quote.
assert.equal(blocked('click'), false);
inDialog = true;
for (const type of ['copy', 'paste', 'drop']) assert.equal(blocked(type), false);
inDialog = false;
document.body.dataset.checkpointStale = 'true';
assert.equal(blocked('copy'), false);               // Recover draft text from an old checkout.
delete document.body.dataset.checkpointStale;
activeRoom = false;
authorField = true;
for (const type of ['copy', 'paste', 'cut', 'drop']) assert.equal(blocked(type), false);
assert.equal(blocked('beforeinput', 'insertFromPaste'), false);
"""
        subprocess.run([shutil.which("node"), "-"], input=harness + guard(PAGES[0]) + checks,
                       text=True, check=True, timeout=10)
