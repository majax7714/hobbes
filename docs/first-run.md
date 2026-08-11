# First run: bringing Hobbes up on an app

A walkthrough for pointing Hobbes at a repo for the first time, in the
order the system is meant to be used. Every step says what it is *for*,
because the order is the design: **deterministic before generative,
enforcement before agents, content before chrome** (build plan,
sequencing rules).

You can stop after any step and still have something useful. Steps 1–4
spend no quota and involve no agents at all.

---

## 0. Build the tools (once)

```sh
cd go
go build -o bin/hobbes-policy  ./cmd/hobbes-policy
go build -o bin/hobbes-web     ./cmd/hobbes-web
go build -o bin/hobbes-session ./cmd/hobbes-session
CGO_ENABLED=0 go build -o bin/hobbes-proxy ./cmd/hobbes-proxy

cd ../web      && npm install && npm run build   # then rebuild hobbes-web
cd ../tsextract && npm install                   # only if the repo has TS/JS
cd ../pipeline && uv sync
```

> **The proxy must be static.** `hobbes-session` mounts the
> `hobbes-proxy` sitting next to it into the sandbox. A dynamically
> linked one fails in the container as `No such file or directory` —
> which is the missing *loader*, not the missing binary, and reads like
> nonsense the first time. `CGO_ENABLED=0` fixes it, and a static binary
> works host-side too.

Put `go/bin` on your `PATH`, or pass `--repo`/`HOBBES_POLICY_BIN`
explicitly. Everything below assumes you are inside the target repo.

---

## 1. `hobbes init` — claim the repo, decide the rules

```sh
hobbes init
```

Scaffolds `.hobbes/` and **gitignores the whole directory** (ADR-012):
in your repos, Hobbes files are personal, not something collaborators
inherit. (This repo is the exception — it versions its own `.hobbes/`
for dogfooding.)

Then open `.hobbes/policies/repo.policy`. This is the one file you
should read before running an agent, because it decides what a session
may do:

```yaml
version: 1
scope: repo
default: escalate          # the default is a question, never a yes

rules:
  - pattern: "*.tfstate*"
    decision: deny
    reason: "tfstate carries secrets"
  - pattern: "git push*"
    decision: deny
    reason: "publishing is the human's — sessions commit, you push"
  - pattern: "pytest*"
    decision: allow
```

**Intent:** `default: escalate` means an unlisted command parks and waits
for you rather than running or failing. Allow the loop you want an agent
to run unattended (tests, builds, formatters). Deny what should never
happen regardless of who asks. Leave everything else to escalate — the
escalation queue is the point, not a failure mode.

Check your reading of it before trusting it:

```sh
hobbes policy resolve "pytest -q"          # -> allow
hobbes policy resolve "git push origin main"  # -> deny, with the reason
hobbes policy resolve "curl https://example.com"  # -> escalate
```

---

## 2. `hobbes ingest` — build the skeleton

```sh
hobbes ingest
```

Runs the deterministic extractors and writes
`.hobbes/derived/{graph,tests,interfaces}.json`, each stamped with the
repo SHA. No LLM, no network, seconds.

Each language is dispatched to its own parser by file extension — `.py`
to the Python extractor, `.tf` to the Terraform one, `.ts/.tsx/.js/.jsx/
.mjs/.cjs` to the ts-morph helper — and the layers merge facts rather
than re-deriving each other's (I-4). If the repo has Terraform and you
have a plan handy, `--tf-plan plan.json` enriches the infra layer;
`.tfstate` is refused outright and always will be.

**Read the output.** It tells you what Hobbes thinks your repo is:

```
ingested /path/to/app @ 9611f8865548 [javascript, typescript]
  graph.json:      104 nodes, 358 module edges, 207 symbols, 235 call edges
  tests.json:      174 tests
  interfaces.json: 12 routes, 0 CLI entry points
```

Anything on stderr starting `WARNING:` is a degradation — a file whose
extraction partly failed, or a module id two languages both wanted. It
is never silent, and it is worth reading before you trust the graph.

---

## 3. `hobbes-web serve` — check the map is *true*

```sh
hobbes-web serve --repo .      # http://127.0.0.1:7777
```

This is the step people skip and shouldn't. The whole system rests on
the derived layer being right about *your* code, and you are the only
one who can tell. It binds loopback only and has no authentication by
design.

Walk the five tabs in the order they're laid out — that order is the
review order:

- **Graph** — pick a module you know cold. Does the inspector's
  "depends on" list match your mental model? Click an edge's `:line`
  citation; it should land on the exact import. Externals are hidden by
  default (a dependency fan-out drowns the layout); toggle them on when
  you want them. Select a node and tick **focus** for anything larger
  than a hundred modules.
- **Tests** — "guarded modules" is the inverse index: what would break
  if you changed this. **"unguarded"** is the number that matters, and
  it is usually uncomfortable the first time.
- **Docs** — empty until step 4. It will tell you so.
- **Diff** — the raw line diff, deliberately last.
- **Sessions** — empty until step 6.

If the graph is wrong here, fix the extractor before spending anything
on step 4. Narrating a wrong skeleton produces confident wrong prose.

`hobbes render` prints the same module graph as Mermaid if you want it
in a markdown file instead.

---

## 4. `hobbes narrate` — the only step that costs quota

```sh
hobbes narrate --dry-run    # what it would do, and how many calls
hobbes narrate
```

Runs a headless, **tool-less** `claude -p` per unit: one module doc per
module node, one behavior index per test file, and one repo-wide
invariant inference pass. Every claim is validated before it is written,
and a claim whose `file:line` pin doesn't resolve is rejected rather
than saved — an unverifiable claim never becomes an artifact.

Start small on a big repo:

```sh
hobbes narrate --only 'app.billing*'
```

It is incremental by default: re-running only regenerates artifacts that
are **missing or stale**, so the second run is cheap.

```sh
hobbes docs status
```

Staleness is blob-level — an artifact is stale when a file it cites has
changed, including uncommitted edits. Badges show up in the Docs tab
immediately; there is no discipline required and no way to forget.

---

## 5. Confirm invariants — the one step Hobbes cannot do for you

Narration wrote `.hobbes/derived/docs/invariants.inferred.yaml`:
statements your code appears to rely on. They are **inert**. Nothing
enforces them, and nothing will, until you move a record by hand:

```sh
$EDITOR .hobbes/derived/docs/invariants.inferred.yaml
# copy the ones you agree with into .hobbes/invariants/I-1-<slug>.yaml,
# set status: confirmed, and give each a compile target
```

**Read every word before promoting one.** An inferred statement is a
guess about intent, and confirming a wrong one versions a false claim
that everything downstream then enforces. Rewrite the prose if it is
nearly right — that is normal, not a failure.

Each record gets a `compile.target`:

| target | for | checked by |
|---|---|---|
| `import-linter` | Python import boundaries | CI **and** `hobbes review` |
| `dep-cruiser` | TS/JS import boundaries | CI **and** `hobbes review` |
| `semgrep` | source patterns that must not appear | CI |
| `rego` | Terraform resource attributes | CI, against `plan -json` |
| `soft` | anything a machine cannot check | a reviewer session |

`soft` is not a cop-out; it is most of them on a real repo, and a soft
invariant with good `guarded_by` tests is stronger than a structured
rule that checks the wrong facet.

```sh
hobbes invariants check      # validates every record; exits 1 with all problems
hobbes invariants compile    # -> .hobbes/derived/compiled/ + a manifest
```

Compiling needs none of those four tools installed — it generates
configs; CI runs them. The manifest tells you the command for each.

---

## 6. `hobbes-session start` — let an agent work, under policy

```sh
hobbes-session start --repo . --role implementer \
  --task "Add a rate limiter to the login route" --claude-cred
```

The session gets a fresh git worktree, a rootless Podman container with
**no network**, an empty environment (no host secrets reach it), and no
raw shell — it reaches commands only through the policy-checked `exec`
tool. It starts oriented: `graph_neighborhood`, `who_calls`,
`tests_guarding`, `get_module_doc`, and `list_invariants` are all
available, so it reads the constraints instead of grepping for them.

Try `--dry-run` first; it prints the exact `podman` argv and MCP config
without running anything.

Watch it in the **Sessions** tab, or from the CLI:

```sh
hobbes-proxy escalations list
hobbes-proxy escalations approve E-20260811T151842Z-776b
hobbes-proxy escalations deny    E-20260811T151842Z-1e38
```

Every call — allowed, refused, or parked — lands in
`~/.hobbes/sessions/<id>/flight.jsonl`. **An approved escalation really
runs**, so read the command before approving it.

For review instead of implementation:

```sh
hobbes-session start --repo . --role reviewer --claude-cred
```

The reviewer's worktree is mounted **read-only** at the kernel level and
its tool list has no Edit, Write, or exec. That is a mount flag, not a
promise.

---

## 7. `hobbes review` — the concept-level gate

```sh
hobbes review main..my-branch
```

The §7 review order in one command:

1. **architecture delta** — added/removed typed edges, with citations
2. **invariants** — judged at *both* ends, so a regression this branch
   introduced is distinguishable from breakage it inherited
3. **behavioral coverage** — new code no test reaches, modules that lost
   every guard, invariants whose guarding tests vanished

Exits **1** when something needs attention, so CI can gate on it alone.
It spends no quota and needs none of the four toolchains. Add `--soft`
to have a reviewer session judge the soft invariants whose scope your
branch actually touched; `--json` gives the whole review for a bot.

The intended reading order is top-down, and the point of the first three
sections is that you rarely reach the line diff.

---

## 8. The refresh loop

```sh
hobbes ingest      # after any merge — seconds, no quota
hobbes narrate     # only regenerates what went stale
hobbes docs status # what moved
```

Put `hobbes ingest && hobbes review $BASE..HEAD` in CI and let the exit
code do the gating.

---

## Things that will bite you

- **Narrating before checking the graph.** Confident prose about a wrong
  skeleton is worse than no prose.
- **Promoting an inferred invariant you skimmed.** It becomes a rule
  everything downstream enforces.
- **Approving an escalation without reading it.** Approval executes.
- **A dynamically linked `hobbes-proxy`.** See step 0.
- **Forgetting to rebuild `hobbes-web` after `npm run build`.** The app
  is embedded in the binary; the old bundle keeps serving.
- **Expecting `soft` invariants to be checked by CI.** They are checked
  by a reviewer session, or by you.

---

## Where the design is written down

`docs/hobbes-architecture.md` and `docs/hobbes-build-plan.md` are the
source of truth. Every decision they don't make has a numbered ADR in
`docs/adr/`. `docs/BUILDLOG.md` is what actually happened, session by
session, and `docs/future_additions.md` is what was deliberately left
undone and why.
