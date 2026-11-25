import { request } from './client'

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `${response.status}`
    try {
      const body = await response.json()
      detail = body.detail || body.message || detail
    } catch {
      // 保留默认状态码错误。
    }
    throw new Error(`接口请求失败：${detail}`)
  }
  return (await response.json()) as T
}

export type JsonRecord = Record<string, any>

export async function listReconciliationViews(
  filters: Record<string, string> = {},
): Promise<{ items: JsonRecord[]; total: number }> {
  const query = new URLSearchParams(
    Object.entries(filters).filter(([, value]) => value.trim()),
  ).toString()
  return parse(await request(`/api/partition-rewrite-reconciliations?${query}`))
}

export async function getReconciliationView(scopeId: string): Promise<JsonRecord> {
  return parse(await request(`/api/partition-rewrite-reconciliations/${encodeURIComponent(scopeId)}`))
}

export async function openReconciliationView(payload: JsonRecord = {}): Promise<JsonRecord> {
  return parse(await request('/api/partition-rewrite-reconciliations/open', {
    method: 'POST',
    body: JSON.stringify(payload),
  }))
}

export async function applyLateCorrection(scopeId: string, payload: JsonRecord): Promise<JsonRecord> {
  return parse(await request(
    `/api/partition-rewrite-reconciliations/${encodeURIComponent(scopeId)}/late-correction`,
    { method: 'POST', body: JSON.stringify(payload) },
  ))
}

export async function reverifyReconciliation(scopeId: string): Promise<JsonRecord> {
  return parse(await request(
    `/api/partition-rewrite-reconciliations/${encodeURIComponent(scopeId)}/reverify`,
    { method: 'POST' },
  ))
}

export async function publishReconciliationSnapshot(
  scopeId: string,
  payload: JsonRecord,
  idempotencyKey: string,
): Promise<JsonRecord> {
  return parse(await request(
    `/api/partition-rewrite-reconciliations/${encodeURIComponent(scopeId)}/snapshots`,
    {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ ...payload, idempotency_key: idempotencyKey }),
    },
  ))
}

export async function listSnapshotPublications(): Promise<{ items: JsonRecord[]; total: number }> {
  return parse(await request('/api/partition-rewrite-snapshots'))
}

export async function getSnapshotPublication(publicationId: string): Promise<JsonRecord> {
  return parse(await request(
    `/api/partition-rewrite-snapshots/${encodeURIComponent(publicationId)}`,
  ))
}

export async function resetReconciliationDemo(): Promise<JsonRecord> {
  return parse(await request('/api/testing/reset-partition-reconciliation', { method: 'POST' }))
}
