export interface Stats {
  loaded: number;
  review: number;
  failed: number;
  inbox: number;
  total_amount: number;
}

export interface DbRecord {
  id: number;
  source_file: string;
  vendor_name?: string | null;
  invoice_date?: string | null;
  invoice_number?: string | null;
  total_amount?: number | null;
  currency?: string | null;
  line_items?: Array<{ description?: string; amount?: number }> | string | null;
  processed_at: string;
  [k: string]: unknown;
}

export interface ReviewItem {
  id: string;
  file: string;
  record: Record<string, unknown>;
  reason: string;
}

export interface Health {
  ok: boolean;
  ollama_reachable: boolean;
  model?: string;
  models?: string[];
  ollama_error?: string;
}

export interface SchemaField {
  name: string;
  type: string;
  required: boolean;
  description: string;
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  stats: () => req<Stats>('/api/stats'),
  health: () => req<Health>('/api/health'),
  records: () => req<DbRecord[]>('/api/records'),
  deleteRecord: (id: number) =>
    req<{ ok: boolean }>(`/api/records/${id}`, { method: 'DELETE' }),
  review: () => req<{ review: ReviewItem[]; failed: Array<Record<string, unknown>> }>('/api/review'),
  approve: (id: string, record?: Record<string, unknown>) =>
    req<{ ok: boolean }>(`/api/review/${encodeURIComponent(id)}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ record: record ?? null }),
    }),
  reject: (id: string) =>
    req<{ ok: boolean }>(`/api/review/${encodeURIComponent(id)}/reject`, { method: 'POST' }),
  inbox: () => req<{ files: Array<{ name: string; size: number; suffix: string }>; supported: string[] }>('/api/inbox'),
  upload: async (files: FileList | File[]) => {
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append('files', f));
    return req<{ ok: boolean; saved: string[] }>('/api/upload', { method: 'POST', body: fd });
  },
  process: (file?: string, lenient = false) =>
    req<{ results: Array<Record<string, string>>; message?: string }>('/api/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file: file ?? null, lenient }),
    }),
  schema: () => req<{ fields: SchemaField[]; checks: Array<{ name: string; description: string }> }>('/api/schema'),
  config: () => req<Record<string, string>>('/api/config'),
};
