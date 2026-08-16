import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  classify,
  decode,
  degradations,
  dependencyCoverage,
  GRAPH_KINDS,
  INDEXERS,
  insideRepo,
  packageOf,
  terminalName,
} from '../index.mjs'

// Real monikers, pasted from scip-python 0.6.6 and scip-typescript 0.4.0
// output during the V2.M0 spike (ADR-027).
const PY = 'scip-python python hobbes 0 `src.hobbes.cli`'
const TS = 'scip-typescript npm betchat-frontend 1.0.0 src/api/`axios.ts`'

test('descriptor kinds are read off real monikers', () => {
  assert.equal(classify(`${PY}/__init__:`), 'meta')
  assert.equal(classify(`${PY}/main().`), 'method')
  assert.equal(classify(`${PY}/main().(argv)`), 'parameter')
  assert.equal(classify(`${PY}/Thing#`), 'type')
  assert.equal(classify(`${PY}/CONSTANT.`), 'term')
  assert.equal(classify(`${TS}/`), 'namespace')
  assert.equal(classify('local 12'), 'local')
})

test('only the four graph kinds survive the filter', () => {
  // ~86% of definitions are parameters, locals and meta (ADR-027).
  assert.ok(GRAPH_KINDS.has('method') && GRAPH_KINDS.has('type'))
  assert.ok(!GRAPH_KINDS.has('parameter'))
  assert.ok(!GRAPH_KINDS.has('local'))
  assert.ok(!GRAPH_KINDS.has('meta'))
})

test('packageOf reads manager and package, never the version', () => {
  assert.equal(packageOf(`${PY}/main().`), 'python:hobbes')
  assert.equal(packageOf(`${TS}/api.`), 'npm:betchat-frontend')
  assert.equal(packageOf('malformed'), '')
})

// A hand-built index in the shape scip.Index.deserialize produces, so the
// decode logic is testable without running an indexer.
function fakeIndex(documents) {
  return { documents, metadata: { project_root: 'file:///stage' } }
}
const DEF = 0x1 // scip.SymbolRole.Definition

test('definitions carry one-based lines and drop noise kinds', () => {
  const idx = fakeIndex([
    {
      relative_path: 'src/a.py',
      occurrences: [
        { symbol: `${PY}/run().`, symbol_roles: DEF, range: [4, 0, 8, 0] },
        { symbol: `${PY}/run().(x)`, symbol_roles: DEF, range: [4, 8, 4, 9] },
        { symbol: 'local 3', symbol_roles: DEF, range: [5, 4, 5, 5] },
      ],
    },
  ])
  const { definitions } = decode(idx)
  assert.equal(definitions.length, 1, 'parameter and local must be filtered out')
  assert.deepEqual(definitions[0], {
    moniker: `${PY}/run().`,
    file: 'src/a.py',
    line: 5, // SCIP is zero-based; the graph is one-based
    end_line: 9,
    kind: 'method',
  })
})

test('references to symbols defined outside the index are not edges', () => {
  const idx = fakeIndex([
    {
      relative_path: 'src/b.py',
      occurrences: [
        { symbol: 'scip-python python python-stdlib 3.11 os/getenv().', symbol_roles: 0, range: [1, 0, 1, 5] },
      ],
    },
  ])
  const { references, packages } = decode(idx)
  assert.equal(references.length, 0, 'stdlib is not a repo edge')
  assert.equal(packages.get('python:python-stdlib'), 1, 'but it is still counted')
})

test('an empty index is reported as degraded, not as an empty repo', () => {
  const idx = fakeIndex([])
  const out = degradations(idx, decode(idx), {})
  assert.ok(out.some((d) => d.stage === 'scip-index'))
})

test('resolving none of the declared dependencies is degradation', () => {
  // The kbet case: exit 0, a plausible index, every third-party edge gone.
  const idx = fakeIndex([
    {
      relative_path: 'src/a.ts',
      occurrences: [{ symbol: `${TS}/api.`, symbol_roles: DEF, range: [0, 0, 0, 3] }],
    },
  ])
  const out = degradations(idx, decode(idx), { declaredDeps: ['axios', 'react'] })
  assert.ok(out.some((d) => d.stage === 'scip-resolve'), 'must notice the gap')
})

test('resolving the declared dependencies is not degradation', () => {
  const idx = fakeIndex([
    {
      relative_path: 'src/a.ts',
      occurrences: [
        { symbol: `${TS}/api.`, symbol_roles: DEF, range: [0, 0, 0, 3] },
        { symbol: 'scip-typescript npm axios 1.0.0 `index.d.ts`/get().', symbol_roles: 0, range: [1, 0, 1, 3] },
      ],
    },
  ])
  const out = degradations(idx, decode(idx), { declaredDeps: ['axios'] })
  assert.equal(out.filter((d) => d.stage === 'scip-resolve').length, 0)
})

// ADR-032. The old test fired only when *every* declared dependency was
// missing, and scip-typescript bundles `typescript`, so that one
// always-resolving package held the condition false forever. Measured on
// kbet staged without node_modules: 1 of 23 resolved, nothing reported.
test("the indexer's own bundled package is not evidence of an environment", () => {
  const idx = fakeIndex([
    {
      relative_path: 'src/a.ts',
      occurrences: [
        { symbol: `${TS}/api.`, symbol_roles: DEF, range: [0, 0, 0, 3] },
        // What an index built with no node_modules is full of.
        { symbol: 'scip-typescript npm typescript 5.9.3 `lib.d.ts`/Array#', symbol_roles: 0, range: [1, 0, 1, 3] },
      ],
    },
  ])
  const declared = { declaredDeps: ['typescript', 'axios', 'react', 'zustand'] }
  const coverage = dependencyCoverage(decode(idx), declared)

  assert.equal(coverage.resolved, 0, 'typescript resolving proves nothing')
  // Excluded from the denominator too: nearly every TS repo declares
  // `typescript`, and a package that can never be credited must not be
  // reported missing either — that would be a permanent false alarm.
  assert.equal(coverage.declared, 3)
  assert.ok(!coverage.missing.includes('typescript'), 'never report the bundled package missing')
  assert.deepEqual(coverage.missing, ['axios', 'react', 'zustand'])

  const out = degradations(idx, decode(idx), declared)
  assert.ok(
    out.some((d) => d.stage === 'scip-resolve'),
    'a near-total resolution failure must be reported',
  )
})

test('dependency coverage is reported as counts, not only as a verdict', () => {
  // The ADR-029 denominator pattern: a repo half-resolved is not a
  // pass/fail, and the number is what a reviewer can act on.
  const idx = fakeIndex([
    {
      relative_path: 'src/a.ts',
      occurrences: [
        { symbol: `${TS}/api.`, symbol_roles: DEF, range: [0, 0, 0, 3] },
        { symbol: 'scip-typescript npm axios 1.0.0 `index.d.ts`/get().', symbol_roles: 0, range: [1, 0, 1, 3] },
      ],
    },
  ])
  const coverage = dependencyCoverage(decode(idx), { declaredDeps: ['axios', 'react'] })
  assert.deepEqual(coverage, { declared: 2, resolved: 1, missing: ['react'] })
})

test('python coverage matches names PEP-503-style, other languages verbatim', () => {
  // C-27's second half: the index resolved into PyYAML while the report
  // went on saying `pyyaml` was missing — distribution names are
  // case-insensitive with -/_/. equivalent, for Python only.
  const idx = fakeIndex([
    {
      relative_path: 'src/a.py',
      occurrences: [
        { symbol: `${PY}/api.`, symbol_roles: DEF, range: [0, 0, 0, 3] },
        { symbol: 'scip-python python PyYAML 6.0.1 `yaml`/load().', symbol_roles: 0, range: [1, 0, 1, 3] },
        { symbol: 'scip-python python tree_sitter 0.25.0 `tree_sitter`/Parser#', symbol_roles: 0, range: [2, 0, 2, 3] },
      ],
    },
  ])
  const py = dependencyCoverage(decode(idx), {
    language: 'python',
    declaredDeps: ['pyyaml', 'tree-sitter', 'httpx'],
  })
  assert.deepEqual(py, { declared: 3, resolved: 2, missing: ['httpx'] })
  // npm treats case and punctuation as identity: no normalisation there.
  const ts = dependencyCoverage(decode(idx), {
    language: 'typescript',
    declaredDeps: ['pyyaml'],
  })
  assert.deepEqual(ts.missing, ['pyyaml'])
})

test('python indexer args carry --environment only when one was computed', () => {
  // C-27: without it, scip-python asks the first pip3 on PATH which
  // environment exists and attributes third-party references to the
  // local project. With no listing the flag must be absent, not empty.
  const base = { stage: '/s', projectName: 'p', projectVersion: '0', output: '/o' }
  const with_ = INDEXERS.python.args({ ...base, environment: '/s.env.json' })
  assert.ok(with_.includes('--environment'))
  assert.equal(with_[with_.indexOf('--environment') + 1], '/s.env.json')
  const without = INDEXERS.python.args(base)
  assert.ok(!without.includes('--environment'))
})

test('terminalName reads the bare name a syntax provider would have seen', () => {
  assert.equal(terminalName(`${PY}/run().`), 'run')
  assert.equal(terminalName(`${PY}/Engine#run().`), 'run')
  assert.equal(terminalName(`${PY}/CONFIG.`), 'CONFIG')
  assert.equal(terminalName(`${PY}/Thing#`), 'Thing')
  assert.equal(terminalName(`${TS}/api.`), 'api')
  assert.equal(terminalName('nonsense'), '')
})

test('references carry the column and name the join needs', () => {
  const idx = fakeIndex([
    {
      relative_path: 'src/a.py',
      occurrences: [{ symbol: `${PY}/run().`, symbol_roles: DEF, range: [4, 0, 8, 0] }],
    },
    {
      relative_path: 'src/b.py',
      occurrences: [{ symbol: `${PY}/run().`, symbol_roles: 0, range: [2, 17, 2, 20] }],
    },
  ])
  assert.deepEqual(decode(idx).references, [
    { file: 'src/b.py', line: 3, col: 17, name: 'run', def_file: 'src/a.py', def_line: 5 },
  ])
})

// V2.M5 (ADR-037): scip-go emits documents for the Go build cache, whose
// paths escape the repo — `../../.cache/go-build/f1/f12bb…-d`. A join that
// trusts `relative_path` invents nodes for files the user has never seen.

test('insideRepo accepts an ordinary repo-relative path', () => {
  assert.equal(insideRepo('cmd/hobbes-policy/main.go'), true)
  assert.equal(insideRepo('main.go'), true)
})

test('insideRepo rejects paths that climb out of the repo', () => {
  assert.equal(insideRepo('../../.cache/go-build/f1/f12bb51-d'), false)
  assert.equal(insideRepo('go/../../elsewhere/x.go'), false)
})

test('insideRepo rejects absolute paths and nothing', () => {
  assert.equal(insideRepo('/etc/passwd'), false)
  assert.equal(insideRepo(''), false)
  assert.equal(insideRepo(undefined), false)
})

test('decode drops documents outside the repo entirely', () => {
  const GO = 'scip-go gomod example.com/x 0 `example.com/x`'
  const idx = fakeIndex([
    {
      relative_path: 'main.go',
      occurrences: [{ symbol: `${GO}/Run().`, symbol_roles: DEF, range: [4, 0, 8, 0] }],
    },
    {
      // The build cache: real occurrences, not this repo's files.
      relative_path: '../../.cache/go-build/f1/f12bb51-d',
      occurrences: [{ symbol: `${GO}/Run().`, symbol_roles: 0, range: [2, 3, 2, 6] }],
    },
  ])
  const out = decode(idx)
  assert.equal(out.definitions.length, 1)
  // The cached document's reference must not become an edge, and must not
  // be counted as external either — it is not a fact about this repo.
  assert.deepEqual(out.references, [])
  assert.deepEqual(out.external, [])
})
