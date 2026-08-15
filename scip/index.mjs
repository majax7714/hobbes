#!/usr/bin/env node
/**
 * Lane B's helper (architecture v2 §3.2, ADR-027).
 *
 * Runs a SCIP indexer over a staging tree, decodes the index, filters it
 * down to what a graph can use, and emits facts JSON for the Python join.
 * Hobbes writes no provider adapters — it runs indexers and consumes their
 * output — so everything here is transport, filtering, and honesty about
 * degradation.
 *
 * Three ADR-027 decisions are implemented here rather than described:
 *
 * - **Decision 1** — `--project-version` is always passed explicitly. Its
 *   default is the git revision, which would put a new version inside every
 *   moniker on every commit.
 * - **Decision 3** — only namespace/type/method/term descriptors become
 *   graph material; parameters, locals and meta are ~86% of definitions and
 *   are dropped here, before the process boundary, not in Python.
 * - **Decision 4** — a zero exit is not a successful index, so degradation
 *   is computed from the index's own contents and reported.
 *
 * Usage:  node index.mjs --config <path-to-json>
 * Config: {stage, language, projectName, projectVersion, declaredDeps[]}
 * Output: facts JSON on stdout; diagnostics on stderr.
 */
import { spawnSync } from 'node:child_process'
import { readFileSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import pkg from '@sourcegraph/scip-typescript/dist/src/scip.js'

const { scip } = pkg
const HERE = dirname(fileURLToPath(import.meta.url))

/** Facts schema version; the Python join refuses anything else. */
export const HELPER_VERSION = 1

/** Indexers we know how to drive, keyed by the language they own. */
export const INDEXERS = {
  python: {
    bin: 'scip-python',
    args: (c) => [
      'index',
      '--cwd', c.stage,
      '--project-name', c.projectName,
      // Decision 1: never let this default to the git revision.
      '--project-version', c.projectVersion,
      '--output', c.output,
      '--quiet',
    ],
  },
  typescript: {
    bin: 'scip-typescript',
    args: (c) => ['index', '--cwd', c.stage, '--output', c.output, '--no-progress-bar'],
  },
}

/**
 * What a SCIP symbol denotes, from its descriptor suffix.
 *
 * `<scheme> <manager> <package> <version> <descriptors>`; the suffix of the
 * last descriptor says what kind of thing it is. Only the first four kinds
 * are graph material (Decision 3).
 */
export function classify(symbol) {
  if (!symbol || symbol.startsWith('local ')) return 'local'
  const parts = symbol.split(' ')
  if (parts.length < 5) return 'malformed'
  const desc = parts.slice(4).join(' ')
  if (/\(\w[^)]*\)$/.test(desc)) return 'parameter'
  if (desc.endsWith('().')) return 'method'
  if (desc.endsWith('#')) return 'type'
  if (desc.endsWith('.')) return 'term'
  if (desc.endsWith('/')) return 'namespace'
  if (desc.endsWith(':')) return 'meta'
  return 'other'
}

/** Descriptor kinds that become graph symbols. */
export const GRAPH_KINDS = new Set(['namespace', 'type', 'method', 'term'])

/**
 * The terminal descriptor's bare name, which is what a syntax provider
 * saw at the call site (ADR-029 matches on it).
 *
 * `…\`src.a\`/Engine#run().` -> `run`;  `…/CONFIG.` -> `CONFIG`.
 */
export function terminalName(symbol) {
  const parts = String(symbol).split(' ')
  if (parts.length < 5) return ''
  const desc = parts.slice(4).join(' ')
  // Strip the descriptor suffix, then take the last path/member segment.
  const bare = desc.replace(/(\(\)\.|#|\.|\/|:)$/, '')
  const seg = bare.split(/[/#.]/).filter(Boolean).pop() ?? ''
  return seg.replace(/`/g, '')
}

/** `<manager>:<package>` for a symbol, or '' when it has no package. */
export function packageOf(symbol) {
  const p = String(symbol).split(' ')
  return p.length >= 4 ? `${p[1]}:${p[2]}` : ''
}

const isDefinition = (occ) =>
  (occ.symbol_roles & scip.SymbolRole.Definition) !== 0

/**
 * Decode an index into definitions, references, and the packages it
 * resolved against.
 *
 * Ranges are SCIP's `[startLine, startChar, endLine, endChar]` (or a
 * 3-element form when the range is single-line), zero-based; graph lines
 * are one-based, so every line is +1 here and nowhere else.
 */
export function decode(index) {
  const definitions = new Map() // moniker -> {file, line, endLine, kind}
  const packages = new Map() // manager:package -> reference count
  const references = []

  for (const doc of index.documents) {
    for (const occ of doc.occurrences) {
      if (!occ.symbol || occ.symbol.startsWith('local ')) continue
      if (!isDefinition(occ)) continue
      const kind = classify(occ.symbol)
      if (!GRAPH_KINDS.has(kind)) continue
      if (definitions.has(occ.symbol)) continue
      const r = occ.range
      definitions.set(occ.symbol, {
        moniker: occ.symbol,
        file: doc.relative_path,
        line: r[0] + 1,
        end_line: (r.length >= 4 ? r[2] : r[0]) + 1,
        kind,
      })
    }
  }

  for (const doc of index.documents) {
    for (const occ of doc.occurrences) {
      if (!occ.symbol || occ.symbol.startsWith('local ')) continue
      const pkgKey = packageOf(occ.symbol)
      if (pkgKey) packages.set(pkgKey, (packages.get(pkgKey) ?? 0) + 1)
      if (isDefinition(occ)) continue
      const target = definitions.get(occ.symbol)
      if (!target) continue // resolves outside this index: not a repo edge
      references.push({
        file: doc.relative_path,
        line: occ.range[0] + 1,
        // Column and name are what let the join tell two same-named
        // occurrences on one line apart (ADR-029).
        col: occ.range[1],
        name: terminalName(occ.symbol),
        def_file: target.file,
        def_line: target.line,
      })
    }
  }

  return { definitions: [...definitions.values()], references, packages }
}

/**
 * Decision 4: a zero exit is not a successful index.
 *
 * scip-typescript on a repo with no node_modules exits 0 in 1.5s and
 * writes a plausible 2.4MB index whose every third-party edge is missing,
 * because the declared dependencies were not there to resolve against.
 * Nothing in the process tells you. So ask the index itself.
 */
export function degradations(index, decoded, config) {
  const out = []
  if (index.documents.length === 0) {
    out.push({
      stage: 'scip-index',
      message: 'the indexer emitted no documents; nothing was analysed',
    })
  }
  const declared = config.declaredDeps ?? []
  if (declared.length) {
    const seen = new Set([...decoded.packages.keys()].map((k) => k.split(':')[1]))
    const missing = declared.filter((d) => !seen.has(d))
    if (missing.length === declared.length) {
      out.push({
        stage: 'scip-resolve',
        message:
          `none of the ${declared.length} declared dependencies were resolved ` +
          `(${missing.slice(0, 3).join(', ')}…) — the environment is probably ` +
          'not installed, so third-party edges are absent rather than nonexistent',
      })
    }
  }
  if (decoded.definitions.length === 0 && index.documents.length > 0) {
    out.push({
      stage: 'scip-decode',
      message: 'documents were indexed but no graph-worthy definitions came out',
    })
  }
  return out
}

function runIndexer(config) {
  const spec = INDEXERS[config.language]
  if (!spec) throw new Error(`no indexer configured for ${config.language}`)
  const bin = join(HERE, 'node_modules', '.bin', spec.bin)
  const proc = spawnSync(bin, spec.args(config), {
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
    timeout: 600_000,
  })
  if (proc.error && proc.error.code === 'ENOENT') {
    throw new Error(
      `${spec.bin} is not installed — run \`npm install\` in the hobbes repo's scip/`,
    )
  }
  if (proc.status !== 0) {
    const detail = String(proc.stderr || proc.stdout || '').trim().slice(-500)
    throw new Error(`${spec.bin} exited ${proc.status}: ${detail}`)
  }
  return proc
}

export function indexStage(config) {
  const proc = runIndexer(config)
  let index
  try {
    index = scip.Index.deserialize(readFileSync(config.output))
  } catch (err) {
    throw new Error(`could not read the SCIP index the indexer wrote: ${err.message}`)
  }
  const decoded = decode(index)
  // The .scip file is an intermediate, never an artifact (ADR-027 clause
  // 6): its metadata.project_root holds the absolute staging path, so
  // identical content staged elsewhere differs in bytes. Nothing about it
  // is propagated, and it is removed once decoded.
  rmSync(config.output, { force: true })
  return {
    helper_version: HELPER_VERSION,
    language: config.language,
    definitions: decoded.definitions,
    references: decoded.references,
    packages: Object.fromEntries(decoded.packages),
    degraded: degradations(index, decoded, config),
    stderr: String(proc.stderr || '').trim().slice(-2000),
  }
}

function main(argv) {
  const at = argv.indexOf('--config')
  if (at === -1 || !argv[at + 1]) {
    process.stderr.write('usage: index.mjs --config <path-to-json>\n')
    process.exitCode = 2
    return
  }
  const config = JSON.parse(readFileSync(argv[at + 1], 'utf8'))
  try {
    process.stdout.write(JSON.stringify(indexStage(config)))
  } catch (err) {
    process.stderr.write(String(err.message ?? err) + '\n')
    // process.exitCode, not process.exit: a hard exit can truncate a large
    // stdout write that is still flushing (the M6 lesson).
    process.exitCode = 1
  }
}

if (process.argv[1] && process.argv[1].endsWith('index.mjs')) main(process.argv)
