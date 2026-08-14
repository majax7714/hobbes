// M0 spike scratch: decode a .scip index and report what is actually in it.
// Not a milestone deliverable — this exists to answer ADR-027's questions
// with real output rather than from the SCIP spec.
import { readFileSync } from 'node:fs'
import pkg from '@sourcegraph/scip-typescript/dist/src/scip.js'

const { scip } = pkg
const index = scip.Index.deserialize(readFileSync(process.argv[2]))

const roleOf = (o) =>
  (o.symbol_roles & scip.SymbolRole.Definition) !== 0 ? 'def' : 'ref'

let occurrences = 0
const defs = new Map() // symbol -> {file, line}
const refs = new Map() // symbol -> count
for (const doc of index.documents) {
  for (const occ of doc.occurrences) {
    if (!occ.symbol || occ.symbol.startsWith('local ')) continue
    occurrences++
    if (roleOf(occ) === 'def') {
      if (!defs.has(occ.symbol))
        defs.set(occ.symbol, { file: doc.relative_path, line: occ.range[0] + 1 })
    } else {
      refs.set(occ.symbol, (refs.get(occ.symbol) || 0) + 1)
    }
  }
}

const out = {
  metadata: {
    tool: index.metadata?.tool_info?.name,
    version: index.metadata?.tool_info?.version,
    project_root: index.metadata?.project_root,
  },
  documents: index.documents.length,
  occurrences,
  distinct_defs: defs.size,
  distinct_referenced: refs.size,
  external_symbols: index.external_symbols?.length ?? 0,
}

if (process.argv[3] === '--samples') {
  const local = [...defs.entries()]
  out.sample_definitions = local.slice(0, 12).map(([s, w]) => ({ symbol: s, at: `${w.file}:${w.line}` }))
  out.sample_external = (index.external_symbols ?? []).slice(0, 8).map((s) => s.symbol)
  const cross = [...refs.entries()].filter(([s]) => !defs.has(s))
  out.sample_unresolved_refs = cross.slice(0, 8).map(([s, n]) => ({ symbol: s, refs: n }))
}

if (process.argv[3] === '--all-defs') {
  out.all_definitions = [...defs.entries()].map(([s, w]) => ({ symbol: s, at: `${w.file}:${w.line}` }))
  delete out.metadata
}

console.log(JSON.stringify(out, null, 2))
