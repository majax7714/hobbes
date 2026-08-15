import assert from 'node:assert/strict'
import { test } from 'node:test'

import { classify, GRAPH_KINDS, packageOf, decode, degradations } from '../index.mjs'

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

test('a reference resolves to the file and line of its definition', () => {
  const idx = fakeIndex([
    {
      relative_path: 'src/a.py',
      occurrences: [{ symbol: `${PY}/run().`, symbol_roles: DEF, range: [4, 0, 8, 0] }],
    },
    {
      relative_path: 'src/b.py',
      occurrences: [{ symbol: `${PY}/run().`, symbol_roles: 0, range: [2, 4, 2, 7] }],
    },
  ])
  const { references } = decode(idx)
  assert.deepEqual(references, [
    { file: 'src/b.py', line: 3, def_file: 'src/a.py', def_line: 5 },
  ])
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
