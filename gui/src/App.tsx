import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, type DbRecord, type Health, type ReviewItem, type Stats } from './api';

type Tab = 'overview' | 'records' | 'review' | 'inbox' | 'schema';

function fmtMoney(n: unknown, cur?: unknown) {
  if (n === null || n === undefined || n === '') return '—';
  const num = Number(n);
  if (Number.isNaN(num)) return String(n);
  return `${num.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${cur ?? ''}`.trim();
}

export default function App() {
  const [tab, setTab] = useState<Tab>('overview');
  const [stats, setStats] = useState<Stats | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [records, setRecords] = useState<DbRecord[]>([]);
  const [review, setReview] = useState<ReviewItem[]>([]);
  const [failed, setFailed] = useState<Array<Record<string, unknown>>>([]);
  const [inbox, setInbox] = useState<Array<{ name: string; size: number; suffix: string }>>([]);
  const [schema, setSchema] = useState<{ fields: Array<{ name: string; type: string; required: boolean; description: string }>; checks: Array<{ name: string; description: string }> } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [log, setLog] = useState<string[]>([]);
  const [query, setQuery] = useState('');
  const [lenient, setLenient] = useState(false);
  const [edits, setEdits] = useState<Record<string, Record<string, string>>>({});

  const refresh = useCallback(async () => {
    setError('');
    try {
      const [s, h, r, rv, ib, sc] = await Promise.all([
        api.stats(), api.health(), api.records(), api.review(), api.inbox(), api.schema(),
      ]);
      setStats(s); setHealth(h); setRecords(r);
      setReview(rv.review); setFailed(rv.failed);
      setInbox(ib.files); setSchema(sc);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to reach API. Is `uvicorn api.server:app --port 8001` running?');
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const pushLog = (m: string) => setLog((l) => [`${new Date().toLocaleTimeString()} ${m}`, ...l].slice(0, 50));

  const doProcess = async (file?: string) => {
    setLoading(true); setError('');
    try {
      const res = await api.process(file, lenient);
      pushLog(`process → ${JSON.stringify(res.results)}`);
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : 'process failed'); }
    finally { setLoading(false); }
  };

  const doUpload = async (files: FileList | File[] | null) => {
    if (!files || files.length === 0) return;
    setLoading(true);
    try {
      const res = await api.upload(files);
      pushLog(`uploaded: ${res.saved.join(', ')}`);
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : 'upload failed'); }
    finally { setLoading(false); }
  };
  const [dragging, setDragging] = useState(false);
  const dragCount = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);

  const doApprove = async (item: ReviewItem) => {
    const edited = edits[item.id];
    let payload: Record<string, unknown> | undefined;
    if (edited) {
      payload = { ...item.record };
      for (const [k, v] of Object.entries(edited)) {
        try { payload[k] = JSON.parse(v); } catch { payload[k] = v; }
      }
    }
    try {
      await api.approve(item.id, payload);
      pushLog(`approved ${item.id}`);
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : 'approve failed'); }
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return records;
    return records.filter((r) => JSON.stringify(r).toLowerCase().includes(q));
  }, [records, query]);

  const tabs: Array<{ id: Tab; label: string; count?: number }> = [
    { id: 'overview', label: 'Overview' },
    { id: 'records', label: 'Records', count: records.length },
    { id: 'review', label: 'Review', count: review.length },
    { id: 'inbox', label: 'Inbox', count: inbox.length },
    { id: 'schema', label: 'Schema' },
  ];

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">◈</div>
          <div><h1>doc-pipeline</h1><p>local doc intelligence</p></div>
        </div>
        <nav className="nav">
          {tabs.map((t) => (
            <button key={t.id} className={tab === t.id ? 'active' : ''} onClick={() => setTab(t.id)}>
              <span>{t.label}</span>
              {t.count !== undefined && <span className={`badge ${t.id === 'review' && t.count > 0 ? 'warn' : ''}`}>{t.count}</span>}
            </button>
          ))}
        </nav>
        <div className="health">
          <div><span className={`dot ${health?.ollama_reachable ? 'ok' : 'down'}`} />
            {health?.ollama_reachable ? `Ollama · ${health.model}` : 'Ollama unreachable'}</div>
          <div style={{ marginTop: 6 }}>API · {error ? 'offline' : 'connected'}</div>
        </div>
      </aside>

      <main className="main">
        <div className="mobile-nav">
          {tabs.map((t) => (
            <button key={t.id} className={`btn small ${tab === t.id ? 'primary' : ''}`} onClick={() => setTab(t.id)}>{t.label}</button>
          ))}
        </div>

        <div className="topbar">
          <div>
            <h2>
              {tab === 'overview' && 'Pipeline overview'}
              {tab === 'records' && 'Loaded records'}
              {tab === 'review' && 'Human review queue'}
              {tab === 'inbox' && 'Inbox & uploads'}
              {tab === 'schema' && 'Extraction schema'}
            </h2>
            <p>Fully local · Ollama structuring · validated into SQLite</p>
          </div>
          <div className="actions">
            <label className="muted" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input type="checkbox" checked={lenient} onChange={(e) => setLenient(e.target.checked)} /> lenient
            </label>
            <button className="btn" onClick={() => void refresh()}>Refresh</button>
            <button className="btn primary" disabled={loading || inbox.length === 0} onClick={() => void doProcess()}>
              {loading ? 'Working…' : `Process inbox (${inbox.length})`}
            </button>
          </div>
        </div>

        {error && <div className="error">⚠ {error}</div>}

        {tab === 'overview' && (
          <>
            <div className="cards">
              <div className="card"><div className="label">Loaded</div><div className="value" style={{ color: 'var(--green)' }}>{stats?.loaded ?? '—'}</div><div className="sub">rows in SQLite</div></div>
              <div className="card"><div className="label">Review</div><div className="value" style={{ color: 'var(--amber)' }}>{stats?.review ?? '—'}</div><div className="sub">needs a human</div></div>
              <div className="card"><div className="label">Failed</div><div className="value" style={{ color: 'var(--red)' }}>{stats?.failed ?? '—'}</div><div className="sub">broken files</div></div>
              <div className="card"><div className="label">Inbox</div><div className="value">{stats?.inbox ?? '—'}</div><div className="sub">pending files</div></div>
              <div className="card"><div className="label">Total amount</div><div className="value">{stats ? stats.total_amount.toLocaleString() : '—'}</div><div className="sub">sum(total_amount)</div></div>
            </div>
            <div className="panel">
              <h3>How it works</h3>
              <p className="muted">data/inbox → ingest → extract (text/OCR) → structure (Ollama strict JSON) → validate (schema + confidence + cross-field) → SQLite, or review queue on low confidence.</p>
            </div>
            {failed.length > 0 && (
              <div className="panel">
                <h3>Failed files</h3>
                <table><thead><tr><th>File</th><th>Reason</th></tr></thead>
                  <tbody>{failed.map((f, i) => (
                    <tr key={i}><td>{String(f.source_file ?? f.file ?? '')}</td><td className="muted">{String(f.reason ?? '')}</td></tr>
                  ))}</tbody></table>
              </div>
            )}
            <div className="panel">
              <h3>Activity</h3>
              {log.length === 0 ? <p className="muted">No actions yet this session.</p> : <div className="log">{log.map((l, i) => <div key={i}>{l}</div>)}</div>}
            </div>
          </>
        )}

        {tab === 'records' && (
          <div className="panel">
            <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
              <input className="search" placeholder="Search vendor, invoice #, amount…" value={query} onChange={(e) => setQuery(e.target.value)} />
            </div>
            {filtered.length === 0 ? <p className="muted">No records yet. Upload docs in the Inbox tab, then Process.</p> : (
              <div style={{ overflowX: 'auto' }}>
                <table>
                  <thead><tr><th>ID</th><th>Vendor</th><th>Date</th><th>Invoice #</th><th>Total</th><th>Source</th><th>Processed</th><th></th></tr></thead>
                  <tbody>{filtered.map((r) => (
                    <tr key={r.id}>
                      <td>{r.id}</td>
                      <td><strong>{String(r.vendor_name ?? '—')}</strong></td>
                      <td>{String(r.invoice_date ?? '—')}</td>
                      <td className="muted">{String(r.invoice_number ?? '—')}</td>
                      <td>{fmtMoney(r.total_amount, r.currency)}</td>
                      <td className="muted">{r.source_file}</td>
                      <td className="muted">{String(r.processed_at ?? '').slice(0, 19).replace('T', ' ')}</td>
                      <td><button className="btn small danger" onClick={() => { if (confirm(`Delete record #${r.id}?`)) void api.deleteRecord(r.id).then(() => { pushLog(`deleted #${r.id}`); void refresh(); }).catch((e) => setError(String(e))); }}>Delete</button></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {tab === 'review' && (
          <>
            {review.length === 0 ? <div className="panel"><p className="muted">Review queue is empty. Low-confidence extractions will appear here with reasons.</p></div> : (
              <div className="review-grid">
                {review.map((item) => (
                  <div className="review-card" key={item.id}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                      <strong>{item.id}</strong>
                      <span className="muted" style={{ fontSize: 12 }}>{item.file}</span>
                    </div>
                    {item.reason && <div className="reason">{item.reason}</div>}
                    <dl className="kv">
                      {Object.entries(item.record).filter(([k]) => k !== '_reason' && k !== 'source_file').map(([k, v]) => (
                        <>
                          <dt key={`dt-${k}`}>{k}</dt>
                          <dd key={`dd-${k}`}>
                            <input
                              defaultValue={typeof v === 'object' ? JSON.stringify(v) : String(v ?? '')}
                              onChange={(e) => setEdits((prev) => ({ ...prev, [item.id]: { ...(prev[item.id] ?? {}), [k]: e.target.value } }))}
                            />
                          </dd>
                        </>
                      ))}
                    </dl>
                    <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                      <button className="btn primary small" onClick={() => void doApprove(item)}>Approve → DB</button>
                      <button className="btn danger small" onClick={() => { if (confirm(`Reject ${item.id}?`)) void api.reject(item.id).then(() => { pushLog(`rejected ${item.id}`); void refresh(); }); }}>Reject</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {tab === 'inbox' && (
          <>
            <div className="panel">
              <h3>Upload documents</h3>
              <div
                className={`drop${dragging ? ' dragging' : ''}`}
                onDragEnter={(e) => { e.preventDefault(); dragCount.current += 1; setDragging(true); }}
                onDragOver={(e) => e.preventDefault()}
                onDragLeave={(e) => { e.preventDefault(); dragCount.current -= 1; if (dragCount.current <= 0) { dragCount.current = 0; setDragging(false); } }}
                onDrop={(e) => {
                  e.preventDefault();
                  dragCount.current = 0; setDragging(false);
                  if (e.dataTransfer.files.length > 0) void doUpload(Array.from(e.dataTransfer.files));
                }}
                onClick={() => fileInput.current?.click()}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileInput.current?.click(); }}
              >
                <p style={{ fontSize: 28 }}>{dragging ? '⇩' : '⤴'}</p>
                <p>{dragging ? 'Drop files to upload' : 'Drag & drop files here, or click to browse'}</p>
                <p className="muted">PDF, PNG, JPG, or CSV — saved straight to <code>data/inbox/</code></p>
                <input
                  ref={fileInput}
                  type="file"
                  multiple
                  accept=".pdf,.png,.jpg,.jpeg,.csv"
                  hidden
                  onChange={(e) => { void doUpload(e.target.files); e.target.value = ''; }}
                />
                <p style={{ margin: '10px 0' }}>
                  <button className="btn small" type="button" onClick={(e) => { e.stopPropagation(); fileInput.current?.click(); }}>
                    Browse files
                  </button>
                </p>
                <p className="muted">Then hit “Process inbox” to run extract → structure → validate → load.</p>
              </div>
            </div>
            <div className="panel">
              <h3>Pending ({inbox.length})</h3>
              {inbox.length === 0 ? <p className="muted">Inbox empty.</p> : (
                <table><thead><tr><th>File</th><th>Size</th><th></th></tr></thead>
                  <tbody>{inbox.map((f) => (
                    <tr key={f.name}><td>{f.name}</td><td className="muted">{(f.size / 1024).toFixed(1)} KB</td>
                      <td><button className="btn small" disabled={loading} onClick={() => void doProcess(f.name)}>Process</button></td></tr>
                  ))}</tbody></table>
              )}
            </div>
          </>
        )}

        {tab === 'schema' && (
          <div className="panel">
            <h3>Fields (single source of truth — prompt + validator + SQLite)</h3>
            <table><thead><tr><th>Name</th><th>Type</th><th>Required</th><th>Description</th></tr></thead>
              <tbody>{schema?.fields.map((f) => (
                <tr key={f.name}><td><code>{f.name}</code></td><td className="muted">{f.type}</td>
                  <td>{f.required ? <span className="pill req">required</span> : <span className="pill opt">optional</span>}</td>
                  <td className="muted">{f.description}</td></tr>
              ))}</tbody></table>
            <h3 style={{ marginTop: 16 }}>Cross-field checks</h3>
            {schema?.checks.map((c) => <p key={c.name} className="muted"><code>{c.name}</code> — {c.description}</p>)}
          </div>
        )}
      </main>
    </div>
  );
}
