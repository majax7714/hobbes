/**
 * The graph view's model layer (ADR-023): turning graph.json into
 * Cytoscape elements under the tab's filters, and answering the focus
 * question — which nodes are within N hops of a selection.
 *
 * Everything here is pure so it can be tested without a canvas; the
 * component owns layout and interaction, this owns what is in the view.
 */

import type { Graph, GraphEdge, GraphNode, NodeKind, Symbol } from '../types'

/** The filter axes ADR-023 fixes: node kind, package, and focus. */
export interface GraphFilters {
  kinds: Set<NodeKind>
  packages: Set<string> | null
  focus: string | null
  depth: number
}

export interface CyNode {
  data: { id: string; label: string; kind: NodeKind; pkg: string; faded?: boolean }
}

export interface CyEdge {
  data: {
    id: string
    source: string
    target: string
    type: string
    label: string
    faded?: boolean
  }
}

export type CyElement = CyNode | CyEdge

/**
 * defaultKinds is every kind except `external`: a repo's dependency
 * fan-out is the largest single source of unreadable layout and is
 * rarely the subject of a review (ADR-023). Hidden by default, one
 * click away.
 */
export function defaultKinds(nodes: GraphNode[]): Set<NodeKind> {
  const kinds = new Set<NodeKind>()
  for (const n of nodes) if (n.kind !== 'external') kinds.add(n.kind)
  return kinds
}

/** allKinds is every kind present in the graph, in a stable order. */
export function allKinds(nodes: GraphNode[]): NodeKind[] {
  const order: NodeKind[] = ['module', 'package', 'external', 'env', 'resource', 'data', 'tf-module']
  const present = new Set(nodes.map((n) => n.kind))
  const known = order.filter((k) => present.has(k))
  const unknown = [...present].filter((k) => !order.includes(k)).sort()
  return [...known, ...unknown]
}

/**
 * packageOf groups a node by its top-level segment. Root-disambiguated
 * ids like `pipeline:tests` stay whole (ADR-008's rule, kept here so the
 * two renderers group alike); `ext:`/`env:`/`tf:` nodes group by their
 * prefix, which is what they are.
 */
export function packageOf(node: GraphNode): string {
  const id = node.id
  const prefix = id.slice(0, id.indexOf(':') + 1)
  if (prefix === 'ext:' || prefix === 'env:' || prefix === 'tf:') return prefix.slice(0, -1)
  // TS/JS ids are paths (ADR-021); Python ids are dotted.
  const bySlash = id.indexOf('/')
  if (bySlash > 0) return id.slice(0, bySlash)
  const byDot = id.indexOf('.')
  return byDot > 0 ? id.slice(0, byDot) : id
}

/** packages lists every package present, sorted. */
export function packages(nodes: GraphNode[]): string[] {
  return [...new Set(nodes.map(packageOf))].sort()
}

/** label strips the prefix a node's kind already conveys. */
export function labelOf(node: GraphNode): string {
  const colon = node.id.indexOf(':')
  if (colon > 0 && ['ext', 'env', 'tf'].includes(node.id.slice(0, colon))) {
    return node.id.slice(colon + 1)
  }
  return node.id
}

/**
 * neighborhood returns the ids within `depth` undirected hops of
 * `start` — the interactive form of graph_neighborhood (ADR-017), and
 * what makes a 600-edge graph readable.
 */
export function neighborhood(edges: GraphEdge[], start: string, depth: number): Set<string> {
  const adjacency = new Map<string, string[]>()
  for (const e of edges) {
    if (!adjacency.has(e.from)) adjacency.set(e.from, [])
    if (!adjacency.has(e.to)) adjacency.set(e.to, [])
    adjacency.get(e.from)!.push(e.to)
    adjacency.get(e.to)!.push(e.from)
  }
  const seen = new Set([start])
  let frontier = [start]
  for (let hop = 0; hop < depth; hop++) {
    const next: string[] = []
    for (const id of frontier) {
      for (const neighbor of adjacency.get(id) ?? []) {
        if (!seen.has(neighbor)) {
          seen.add(neighbor)
          next.push(neighbor)
        }
      }
    }
    if (next.length === 0) break
    frontier = next
  }
  return seen
}

/**
 * buildElements applies the filters and returns Cytoscape elements.
 *
 * Kind and package filters *remove*; focus only *fades*, so the shape of
 * the rest of the system stays visible while one node is being read.
 * Edges survive only when both endpoints do — a dangling edge would
 * claim a dependency on something the view is not showing.
 */
export function buildElements(graph: Graph, filters: GraphFilters): CyElement[] {
  const visible = new Map<string, GraphNode>()
  for (const node of graph.nodes) {
    if (!filters.kinds.has(node.kind)) continue
    if (filters.packages && !filters.packages.has(packageOf(node))) continue
    visible.set(node.id, node)
  }

  const focused =
    filters.focus && visible.has(filters.focus)
      ? neighborhood(graph.module_edges, filters.focus, filters.depth)
      : null

  const nodes: CyNode[] = []
  for (const id of [...visible.keys()].sort()) {
    const node = visible.get(id)!
    nodes.push({
      data: {
        id: node.id,
        label: labelOf(node),
        kind: node.kind,
        pkg: packageOf(node),
        faded: focused ? !focused.has(node.id) : false,
      },
    })
  }

  const edges: CyEdge[] = []
  const seen = new Set<string>()
  for (const edge of graph.module_edges) {
    if (!visible.has(edge.from) || !visible.has(edge.to)) continue
    const id = `${edge.from}|${edge.type}|${edge.to}`
    if (seen.has(id)) continue
    seen.add(id)
    edges.push({
      data: {
        id,
        source: edge.from,
        target: edge.to,
        type: edge.type,
        // `imports` is the overwhelming default; labelling it would
        // bury the edge types that actually carry information.
        label: edge.type === 'imports' ? '' : edge.type,
        faded: focused ? !(focused.has(edge.from) && focused.has(edge.to)) : false,
      },
    })
  }
  // Nodes before edges: Cytoscape requires an edge's endpoints to exist.
  return [...nodes, ...edges]
}

/** Everything the inspector shows about one node. */
export interface NodeDetail {
  node: GraphNode
  symbols: Symbol[]
  outgoing: GraphEdge[]
  incoming: GraphEdge[]
}

export function nodeDetail(graph: Graph, id: string): NodeDetail | null {
  const node = graph.nodes.find((n) => n.id === id)
  if (!node) return null
  return {
    node,
    symbols: graph.symbols
      .filter((s) => s.module === id)
      .sort((a, b) => a.line - b.line),
    outgoing: graph.module_edges.filter((e) => e.from === id),
    incoming: graph.module_edges.filter((e) => e.to === id),
  }
}
