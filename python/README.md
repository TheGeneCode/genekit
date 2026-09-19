# genekit (Python)

The Python language dir. Tags are prefixed `py-vX.Y.Z`. Admission rules and the quality gate live in
[CHARTER.md](https://github.com/TheGeneCode/genekit/blob/main/CHARTER.md); promotion candidates live in [ledger/CANDIDATES.md](https://github.com/TheGeneCode/genekit/blob/main/ledger/CANDIDATES.md).

Both tables below are filled in by promotions — see [the repo README](https://github.com/TheGeneCode/genekit/blob/main/README.md) for the consumer
install recipe.

A personal library, published rather than offered: the `py-vX.Y.Z` tags are the only contract, and
`main` is a working branch. See the
[repo README](https://github.com/TheGeneCode/genekit/blob/main/README.md) for what that means and
[CONTRIBUTING.md](https://github.com/TheGeneCode/genekit/blob/main/CONTRIBUTING.md) for why issues and
pull requests are not being taken.

## Module inventory
| Module | Provides | Since |
|---|---|---|
| `logging` | opinionated root config (rich/plain/none console on stderr), optional size-based file rotation, scoped per-file routing, dedicated file loggers | py-v0.1.0 |
| `tz` | timezone resolution that degrades instead of crashing, explicit naive-input policy, epoch/datetime display formatting that always converts first | py-v0.3.0 |
| `atomic_write` | write-then-replace so a reader never sees a half-written file; unique temp name always, cleanup on any failure, raise-or-ignore as a parameter | py-v0.4.0 |

The rich console needs the `rich` extra — `uv add "genekit[rich] @ git+..."`. Without it,
`console="rich"` degrades silently to a plain stderr handler.

`genekit.tz` needs an IANA tz database to resolve zone names. CPython ships one on Linux and macOS
but not on Windows, where without it *every* lookup fails — including `"UTC"`. Add the `tzdata`
extra there — `uv add "genekit[tzdata] @ git+..."`. Without it, `resolve_tz` logs a warning and
degrades to the system local zone.

## Consumers registry

Every repo that depends on genekit, and the tag it is pinned to. These repos are private — this is a
maintenance ledger, not a directory of things you can go and read. It exists so that a breaking change
has to name, in writing, every caller it breaks before it can be released; a registry that lags
reality is worse than no registry, because the next break will trust it.

| Module | Consumer repo | Pinned tag |
|---|---|---|
| `logging` | remove-the-bloat | py-v0.3.1 |
| `logging` | TTS | py-v0.1.0 |
| `logging` | MeadowLark | py-v0.3.1 |
| `logging` | personal-agents (price-tracker) | py-v0.3.1 |
| `logging` | quicknote | py-v0.3.1 |
| `tz` | MeadowLark | py-v0.3.1 |
| `tz` | personal-agents | py-v0.3.1 |
