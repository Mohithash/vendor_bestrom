@AGENTS.md

<!--
  SOURCE OF TRUTH: vendor/bestrom/tools/CLAUDE.md
  The tree-root copy is written by repo <copyfile>; edits there are lost on sync.
-->

Claude Code specifics on top of AGENTS.md:

* The project-scope MCP config is the root `.mcp.json`. Claude Code asks once
  whether to trust it; approve it or the `bestrom` tools will not appear.
* No bootstrap step. `.mcp.json` runs
  `uv run --directory vendor/bestrom/tools/mcp bestrom-mcp`, which creates the
  venv on the first connection; the venv holds absolute shebangs, so it is
  machine-local and git-ignored. It does need `uv` and Python 3.11+ on PATH.
* Long tools (`repo_sync`, `verify_image` on a cold page cache) can exceed the
  default MCP timeout. `.mcp.json` sets `timeout` to 600000 ms; raise
  `MCP_TIMEOUT` in the environment if a call still times out.
* Builds outlive the session on purpose. `build_start` returns a `job_id` and a
  log path; poll with `build_status` in a later turn rather than holding a tool
  call open.
