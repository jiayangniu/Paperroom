---
name: open
description: Open a manuscript's Paperroom workspace, or enable it when the author explicitly asks Paperroom to manage this manuscript.
disable-model-invocation: true
---

# Open Paperroom

Use the manuscript folder named by the author, or the current local project folder when it clearly identifies one manuscript. If the window contains several papers, ask which one. Pass its absolute path as `project` on every call. A path, port or link from another chat may point to a different paper.

- **Open or resume** (including this shortcut by itself). Call `open_writing_workspace(project=…)` once. For a coauthor's copy use the folder on this computer. If the project is unmanaged, ask whether the author wants Paperroom to manage this folder.
- **Start managing this manuscript** (for example, “用 Paperroom 管理这篇论文”). Call `activate_project(project=…)` once. The result already contains the workspace link.

Show the returned `room_url` as a clickable link. Opening the workspace completes this request. Leave the outline and manuscript as they are until the author requests further work. If the client denies the call, identify that specific tool and report its error. Wait for the author to approve it before retrying. Do not substitute shell commands or guess a URL.
