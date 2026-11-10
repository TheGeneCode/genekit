# genekit

- **[CHARTER.md](CHARTER.md) is binding.** Read it before touching `python/src/`; when a request
  conflicts with it, the charter wins.
- Python package lives in `python/` (src layout, `uv`). Every `uv` command runs from there.
- Fast verification tier (same as CI `lint` + `test`):
  `cd python && uv run ruff check . && uv run ruff format --check . && uv run basedpyright && uv run pytest -q`
- Fresh clone/worktree: `git config core.hooksPath .githooks` (pre-commit lint, pre-push
  private-name scan).
- `ledger/CANDIDATES.md` rules: CHARTER.md § Ledger hygiene, enforced by
  `python/tests/test_ledger_hygiene.py` — run it after any ledger edit.
- No `uv add`: a runtime dependency is a charter change, not a code change.
- Repo is public. Only `docs/` and `plans/` (both gitignored) may name private repos — known
  defects go in `docs/BACKLOG.md`; finished plans move to `plans/complete/`.
