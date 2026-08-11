/**
 * The shapes the API serves.
 *
 * Extractor artifacts (graph/tests/interfaces) pass through the server
 * untouched, so these mirror the pipeline's schema v3 (ADR-006/021) and
 * are the one place the surface restates it — the reason `npm run build`
 * typechecks before it bundles.
 */

export interface Pin {
  path: string
  line: number
}

export type NodeKind =
  | 'module'
  | 'package'
  | 'external'
  | 'env'
  | 'resource'
  | 'data'
  | 'tf-module'

export interface GraphNode {
  id: string
  kind: NodeKind
  path?: string
  name?: string
}

export interface GraphEdge {
  from: string
  to: string
  type: string
  evidence?: Pin[]
}

export interface Symbol {
  id: string
  module: string
  name?: string
  qualname?: string
  kind: string
  line: number
  end_line?: number
}

export interface Graph {
  schema_version: number
  sha: string
  dirty: boolean
  languages: string[]
  nodes: GraphNode[]
  module_edges: GraphEdge[]
  symbols: Symbol[]
  symbol_edges: GraphEdge[]
  extraction_errors?: { path?: string; stage?: string; error: string }[]
}

export interface TestCase {
  id: string
  file: string
  line: number
  framework?: string
  symbol?: string
  reaches: string[]
  reaches_modules: string[]
}

export interface Tests {
  schema_version: number
  sha: string
  dirty: boolean
  tests: TestCase[]
}

export interface Route {
  framework: string
  method: string
  path: string
  handler: string
  file: string
  line: number
}

export interface Interfaces {
  routes: Route[]
  cli_entry_points: { name: string; target: string; source: string }[]
}

/** Server-computed, not an artifact field. */
export type Badge = 'fresh' | 'stale' | 'broken'

export interface Overview {
  repo: string
  root: string
  head: string
  branch: string
  ingested: boolean
  narrated: boolean
  sha?: string
  dirty: boolean
  behind: boolean
  schema_version?: number
  languages: string[]
  counts: Record<string, number>
  hint?: string
}

export interface Claim {
  text: string
  pins: Pin[]
}

export interface DocEntry {
  kind: 'module-doc' | 'test-doc' | 'inferred-invariants'
  id: string
  path?: string
  sha?: string
  status: Badge
  changed: string[]
  error?: string
}

export interface ModuleDoc {
  id: string
  path: string
  sha: string
  purpose: Claim
  responsibilities: Claim[]
  gotchas: Claim[]
  status: Badge
  changed: string[]
}

export interface Behavior {
  test: string
  text: string
  pins: Pin[]
  doc_id: string
  status: Badge
}

export interface Invariant {
  id: string
  statement: string
  scope: string
  status: string
  guarded_by?: string[]
  evidence: Pin[]
}

export interface Invariants {
  id: string
  sha: string
  invariants: Invariant[]
  status: Badge
  changed: string[]
}

export interface SourceFile {
  path: string
  lines: string[]
  truncated: boolean
  bytes: number
}

export interface DiffFile {
  path: string
  added: number
  removed: number
  binary: boolean
}

export interface DiffResult {
  mode: 'working-tree' | 'range'
  base: string
  head: string
  files: DiffFile[]
  patch: string
  truncated: boolean
}

export interface RefInfo {
  name: string
  kind: 'branch' | 'tag' | 'commit'
  subject?: string
}

export interface SessionSummary {
  id: string
  role: string
  events: number
  allowed: number
  denied: number
  escalated: number
  pending: number
  first_seen?: string
  last_seen?: string
  last_command?: string
  active: boolean
}

/** One flight-recorder line (ADR-015). */
export interface FlightEvent {
  ts: string
  session: string
  role: string
  tool: string
  argv: string[]
  policy_rule: string
  decision: 'allow' | 'deny' | 'escalate'
  exit: number | null
  sha: string
  escalation?: { id: string; resolution?: string; approver?: string }
}

export interface FlightPage {
  session: string
  events: FlightEvent[]
  /** The cursor this page was read from. */
  after: number
  next: number
  torn: number
  more: boolean
}

export interface Escalation {
  id: string
  session: string
  role: string
  repo: string
  command: string
  dir?: string
  policy_rule: string
  reason?: string
  requested_at: string
  expires_at: string
  status: string
  resolved_at?: string
  approver?: string
  effective_status: 'pending' | 'approved' | 'denied' | 'expired'
  seconds_left: number
  resolvable: boolean
}
