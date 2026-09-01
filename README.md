# genekit

> **A personal library, published rather than offered.** genekit exists to serve five of my own
> applications and is developed entirely for that purpose. You are welcome to read it, fork it, or
> depend on it — it is MIT — but nothing here is a product. **The only contract is a pinned tag:**
> `py-vX.Y.Z` tags are annotated, never moved and never deleted, and that is the whole of what I
> promise. `main` is a working branch and can change under you. Issues are off and pull requests are
> closed without review; [CONTRIBUTING.md](CONTRIBUTING.md) says why, and names the one exception.

A personal, cross-app **decisions library**. It holds two kinds of code: opinionated glue that
encodes a decision I have already made and do not want to re-make per app (how logging is set up,
how config is discovered, how a URL is normalized), and genuinely hard logic that is used by three
or more apps and is worth writing carefully exactly once.

genekit is explicitly **not** a utils grab-bag. A function does not belong here because it is small
and reusable in principle — it belongs here because it has been written three times already and the
copies have started to disagree. Admission is gated by the rule of three and the quality bar in
[CHARTER.md](CHARTER.md); that document, not this one, is the authority on what may enter.

## Layout

```
genekit/
├── CHARTER.md          # admission rules + quality gate (cross-language, authoritative)
├── ledger/
│   └── CANDIDATES.md   # promotion state machine: sightings → ripe → promoted
└── python/             # the Python language dir (the only one today)
    ├── pyproject.toml
    ├── README.md       # module inventory + consumers registry
    ├── CHANGELOG.md
    ├── src/genekit/
    └── tests/
```

Each language gets **one sibling directory** with its own package tooling, its own `CHANGELOG.md`,
and its own tag prefix — `py-vX.Y.Z` today, `cs-vX.Y.Z` or similar later. Adding a language means
adding a directory, never restructuring the ones that exist.

`CHARTER.md` and `ledger/` sit at the root because they are cross-language: the rule of three counts
sightings of a *capability*, not of a Python function, and the same capability may eventually be
promoted into more than one language dir. They are never duplicated per language.

## How Python apps consume it

```
uv add "genekit @ git+https://github.com/TheGeneCode/genekit#subdirectory=python" --tag py-vX.Y.Z
```

which produces in the consumer's `pyproject.toml`:

```toml
[project]
dependencies = ["genekit"]

[tool.uv.sources]
genekit = { git = "https://github.com/TheGeneCode/genekit", subdirectory = "python", tag = "py-vX.Y.Z" }
```

Consumers pin **tags only — never a branch**. A branch pin means an unrelated push to `main` can
silently change a consumer's behaviour on its next lock refresh, which is precisely the failure mode
a shared library is supposed to eliminate. Every consumer and its pinned tag is recorded in the
consumers registry in [python/README.md](python/README.md).

## How code gets in

Code enters through the ledger, not through a commit. During normal app work, agents append
*sightings* to [ledger/CANDIDATES.md](ledger/CANDIDATES.md) — "here is a third place that does this".
Once a capability has three independent sightings across at least two repos it becomes `ripe`, and
the `/genekit promote` skill is what moves it from ripe to a real module: generalize the API, meet
the charter's quality gate, register the consumers, cut the tag. **Committing a new module outside
that workflow is forbidden**, including when it seems obviously useful, because the workflow is the
only thing standing between this repo and the grab-bag it is meant not to be.

## Growth guardrails

Python stays a **single package**. It splits into a uv workspace only if some submodule genuinely
needs to version independently of the rest — a real need, not an anticipated one.

Keep the public surface small. Every exported symbol is a promise to every consumer, and the cost of
a shared library is paid at the API boundary. Deleting modules that no consumer uses is allowed and
encouraged at major bumps; a shrinking library is a healthy one.

## License

MIT — see [LICENSE](LICENSE). The license governs the code; [CHARTER.md](CHARTER.md) governs what is
allowed to join it.
