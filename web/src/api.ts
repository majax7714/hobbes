/**
 * The API client. Every endpoint is read-only except the two escalation
 * verdicts (ADR-022), and every failure carries the server's hint — the
 * command that would produce the missing data — so tabs can render
 * "not ingested yet" as guidance rather than as an error.
 */

import type {
  Behavior,
  DiffResult,
  DocEntry,
  Escalation,
  FlightPage,
  Graph,
  Interfaces,
  Invariants,
  ModuleDoc,
  Overview,
  RefInfo,
  SessionSummary,
  SourceFile,
  Tests,
} from './types'

/** ApiError carries the server's hint alongside the message. */
export class ApiError extends Error {
  status: number
  hint: string
  constructor(status: number, message: string, hint = '') {
    super(message)
    this.status = status
    this.hint = hint
  }
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    let hint = ''
    try {
      const body = await res.json()
      if (body?.error) message = body.error
      if (body?.hint) hint = body.hint
    } catch {
      // A non-JSON error body (a proxy, say) leaves the status text.
    }
    throw new ApiError(res.status, message, hint)
  }
  return (await res.json()) as T
}

async function post<T>(path: string): Promise<T> {
  const res = await fetch(path, { method: 'POST', headers: { Accept: 'application/json' } })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new ApiError(res.status, body?.error ?? `${res.status} ${res.statusText}`, body?.hint ?? '')
  }
  return body as T
}

export const api = {
  overview: () => get<Overview>('/api/overview'),
  graph: () => get<Graph>('/api/graph'),
  tests: () => get<Tests>('/api/tests'),
  interfaces: () => get<Interfaces>('/api/interfaces'),

  docs: () => get<{ artifacts: DocEntry[] }>('/api/docs'),
  moduleDoc: (id: string) => get<ModuleDoc>(`/api/docs/module/${encodePath(id)}`),
  behaviors: () => get<{ behaviors: Behavior[]; hint?: string }>('/api/behaviors'),
  invariants: () => get<Invariants>('/api/docs/invariants'),

  source: (path: string) => get<SourceFile>(`/api/source?path=${encodeURIComponent(path)}`),
  refs: () => get<{ refs: RefInfo[]; head: string }>('/api/refs'),
  diff: (base = '', head = '') =>
    get<DiffResult>(
      `/api/diff?base=${encodeURIComponent(base)}&head=${encodeURIComponent(head)}`,
    ),

  sessions: () => get<{ sessions: SessionSummary[]; log_dir: string }>('/api/sessions'),
  flight: (id: string, after = 0) =>
    get<FlightPage>(`/api/sessions/${encodeURIComponent(id)}/flight?after=${after}`),
  escalations: (all = false) =>
    get<{ escalations: Escalation[] }>(`/api/escalations${all ? '?all=1' : ''}`),
  resolve: (id: string, verdict: 'approve' | 'deny') =>
    post<{ escalation: Escalation }>(`/api/escalations/${encodeURIComponent(id)}/${verdict}`),
}

/**
 * Module ids may contain "/" (TS/JS ids are repo-relative paths,
 * ADR-021), and the route matches the rest of the path — so each
 * segment is escaped but the separators are kept.
 */
export function encodePath(id: string): string {
  return id.split('/').map(encodeURIComponent).join('/')
}
