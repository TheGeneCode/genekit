# genekit (Python)

The Python language dir. Tags are prefixed `py-vX.Y.Z`. Admission rules and the quality gate live in
[../CHARTER.md](../CHARTER.md); promotion candidates live in [../ledger/CANDIDATES.md](../ledger/CANDIDATES.md).

Both tables below are filled in by promotions — see [../README.md](../README.md) for the consumer
install recipe.

## Module inventory
| Module | Provides | Since |
|---|---|---|
| `logging` | opinionated root config (rich/plain/none console on stderr), scoped per-file routing, dedicated file loggers | py-v0.1.0 |

The rich console needs the `rich` extra — `uv add "genekit[rich] @ git+..."`. Without it,
`console="rich"` degrades silently to a plain stderr handler.

## Consumers registry
| Module | Consumer repo | Pinned tag |
|---|---|---|
| `logging` | remove-the-bloat | py-v0.1.0 |
| `logging` | Plex | py-v0.1.0 |
| `logging` | TTS | py-v0.1.0 |
| `logging` | MeadowLark | py-v0.1.0 |
