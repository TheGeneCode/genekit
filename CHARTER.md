# genekit Charter

> **On the voice.** The first person here is one person: genekit is a personal library, and this is a
> working instrument I hold myself and my agents to during real tasks — not a proposal, not a
> governance template, and not an invitation to negotiate. The flat imperatives and the absence of
> hedging are the point. It is deliberately harder on additions than a general-purpose library would
> be, because the failure mode it defends against is my own convenience.

This document is the authority on what may enter genekit and the bar it must clear. It binds agents
and humans equally. When a request conflicts with this charter, the charter wins: say so, cite the
rule, and stop. "The user asked me to add it" is not an exemption — the charter exists precisely to
survive the moment when adding something feels convenient.

---

## Admission (rule of three)

A capability enters genekit only after **three independent sightings across at least two repos**,
each recorded in [ledger/CANDIDATES.md](ledger/CANDIDATES.md) with its repo, path, line range, and
date. Independent means three places that genuinely solved the same problem on their own — not one
implementation imported three times, and not three call sites of the same function. Until the third
sighting lands, the capability stays `candidate` and no module is written.

There are **no speculative helpers and no "while I'm here" additions**. If a function looks certain
to be needed by a future app, that certainty costs nothing to test: leave it in the app, and let the
third sighting prove it. Code that enters on prediction rather than evidence is the exact material
that turns a decisions library into a grab-bag, and it is far harder to delete later than to decline
now.

**Never reimplement what the standard library or a mature third-party library already does well.**
Before proposing a promotion, name the stdlib or library alternative and state why it is
insufficient. If no such statement can be made honestly, the answer is to use the existing library.

A thin wrapper is admissible **only when it encodes a decision** — a set of defaults, a configuration
choice, a composition of several calls that must always happen together. "Our logging setup" is a
decision: it fixes handlers, formats, and routing that would otherwise be re-argued in every app. A
wrapper that renames an API, reorders its arguments, or saves a line of typing encodes no decision
and is rejected on sight.

---

## Generalization rules

**Public API names must be app-agnostic.** The litmus test is `season_logging` → `scoped_logging`:
if a name only makes sense to someone who knows the app it came from, it is the wrong name. Strip
domain vocabulary from the promoted API even when the originating code will keep using it locally;
the module belongs to every future consumer, not to the app that happened to write it first.

**Parameters over hardcoded values.** Every opinionated default must be overridable by keyword
argument. Defaults are what makes genekit a decisions library, so keep them opinionated and useful —
but a default that cannot be overridden is a constraint on every consumer forever, and the consumer
that needs to override it is the one who cannot afford to fork.

**Zero hard runtime dependencies.** The base package imports stdlib only. Optional integrations go
behind extras (`genekit[rich]`) and every such integration must **degrade gracefully with a
documented fallback** when the extra is absent — importing genekit must never raise because an
optional package is missing. Adding a hard dependency imposes it on all consumers at once and is a
charter change, not a code change.

**No environment assumptions.** No absolute paths, no user- or machine-specific environment
variables, no assumption about repo layout, OS, or where a config file lives. Anything
environment-shaped is an argument the caller supplies. Code that works only on my machine is not
shared code.

---

## Quality gate

This gate applies to **every public symbol** and is enforced **before any release tag is cut**. It is
not a checklist to be argued down when a change feels small: the entire justification for centralizing
this code is that it gets written to a standard no single app would pay for.

- **Types and lint.** Full type hints on every public signature. The package ships `py.typed`.
  `uv run ruff check .` reports **0 findings** — not "only warnings", zero.
- **Docstrings.** Every public function carries Args / Returns / Raises and **at least one runnable
  example**. Runnable means it works when pasted into a REPL, with no invented variables.
- **Tests.** Happy path plus an edge matrix: empty, `None`, unicode, boundary values, and
  concurrency where the code can be reached concurrently. **Hypothesis property tests are required
  for all pure logic** — if a function is deterministic and side-effect-free, its invariants get
  stated as properties, not sampled by three hand-picked cases.
- **Agent review.** A **qa-boundary-tester agent review** of the new or changed module, with its
  findings addressed, before the tag. Addressed means fixed or explicitly rejected with a reason in
  the pull of the promotion commit — not silently ignored.
- **Changelog.** A `CHANGELOG.md` entry in the language directory.

---

## Releases & consumers

Versioning is **semver per language**, with annotated tags prefixed by the language: `py-vX.Y.Z`.
Each language dir versions independently; a Python release says nothing about any other language.

A **breaking change requires a major bump plus migration notes** in that language's `CHANGELOG.md`,
and those notes must **name every consumer** listed in the consumers registry
([python/README.md](python/README.md)). If naming the affected consumers is too tedious to do, the
break is too expensive to make — that friction is deliberate.

**Every promotion or migration updates the consumers registry in the same commit.** A registry that
lags reality is worse than no registry, because the next breaking change will trust it.
