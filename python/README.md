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

The rich console needs the `rich` extra — `uv add "genekit[rich] @ git+..."`. Without it,
`console="rich"` degrades silently to a plain stderr handler.

## Consumers registry

Every repo that depends on genekit, and the tag it is pinned to. These repos are private — this is a
maintenance ledger, not a directory of things you can go and read. It exists so that a breaking change
has to name, in writing, every caller it breaks before it can be released; a registry that lags
reality is worse than no registry, because the next break will trust it.

| Module | Consumer repo | Pinned tag |
|---|---|---|
| `logging` | remove-the-bloat | py-v0.1.0 |
| `logging` | Plex | py-v0.1.0 |
| `logging` | TTS | py-v0.1.0 |
| `logging` | MeadowLark | py-v0.1.0 |
| `logging` | personal-agents (price-tracker) | py-v0.2.0 |
