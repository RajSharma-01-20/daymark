import { ChangeEvent, DragEvent, useCallback, useEffect, useState } from 'react';

const API = import.meta.env.VITE_DLP_URL ?? 'http://localhost:8102';
const MAX_BYTES = 100_000;

type Finding = { type: string; count: number };
type ScanResult = { id: number; action: 'clear' | 'redacted'; findings: Finding[]; sanitized_text: string; raw_content_saved: false; created_at: string };
type AuditItem = { id: number; user: string; source: 'text' | 'file'; action: 'clear' | 'redacted'; findings: Record<string, number>; created_at: string };
type User = { name: string; subject: string };
type Section = 'inspect' | 'audit';

async function api<T>(path: string, csrf = '', init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (init.method && init.method !== 'GET' && csrf) headers.set('X-CSRF-Token', csrf);
  const response = await fetch(API + path, { ...init, headers, credentials: 'include' });
  if (!response.ok) {
    let message = 'Request failed (' + response.status + ')';
    try { const body = await response.json(); message = body.detail ?? message; } catch { /* Keep the safe fallback. */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

function prettyKind(kind: string) {
  return ({ PAYMENT_CARD: 'Payment card', AADHAAR: 'Aadhaar number', EMAIL: 'Email address', PHONE: 'Phone number', SECRET: 'Password or secret' } as Record<string, string>)[kind] ?? kind;
}

function localTime(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

export default function DlpApp() {
  const [user, setUser] = useState<User | null>(null);
  const [csrf, setCsrf] = useState('');
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const [section, setSection] = useState<Section>('inspect');
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [audit, setAudit] = useState<AuditItem[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState('');
  const loginError = new URLSearchParams(window.location.search).get('error');

  const flash = (message: string) => { setNotice(message); window.setTimeout(() => setNotice(''), 3800); };

  const loadAudit = useCallback(async () => {
    if (!csrf || !isAdmin) return;
    setAuditLoading(true);
    setAuditError('');
    try {
      const page = await api<{ items: AuditItem[] }>('/api/audit?limit=50', csrf);
      setAudit(page.items);
    } catch (error) {
      setAuditError(error instanceof Error ? error.message : 'Could not load the audit log.');
    } finally { setAuditLoading(false); }
  }, [csrf, isAdmin]);

  useEffect(() => {
    api<{ authenticated: boolean; user?: User; csrf_token?: string; is_admin?: boolean }>('/api/me')
      .then(info => {
        if (!info.authenticated || !info.user || !info.csrf_token) return;
        setUser(info.user);
        setCsrf(info.csrf_token);
        setIsAdmin(!!info.is_admin);
      })
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { if (section === 'audit') void loadAudit(); }, [section, loadAudit]);

  function acceptFile(selected: File | undefined) {
    if (!selected) return;
    const suffix = selected.name.split('.').pop()?.toLowerCase();
    if (!['txt', 'md', 'csv'].includes(suffix ?? '')) { flash('Choose a .txt, .md, or .csv text file.'); return; }
    if (selected.size > MAX_BYTES) { flash('Files must be 100 KB or smaller.'); return; }
    setFile(selected);
    setText('');
    setResult(null);
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    acceptFile(event.target.files?.[0]);
    event.target.value = '';
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    acceptFile(event.dataTransfer.files?.[0]);
  }

  async function scan() {
    if (!file && !text.trim()) { flash('Paste text or choose a file to inspect.'); return; }
    setBusy(true);
    setResult(null);
    try {
      let scanned: ScanResult;
      if (file) {
        const body = new FormData();
        body.append('file', file);
        scanned = await api<ScanResult>('/api/scan-file', csrf, { method: 'POST', body });
      } else {
        scanned = await api<ScanResult>('/api/scan', csrf, { method: 'POST', body: JSON.stringify({ text }) });
      }
      setResult(scanned);
      if (isAdmin) void loadAudit();
      flash(scanned.action === 'redacted' ? 'Sensitive patterns found and redacted in the preview.' : 'No configured sensitive patterns were detected.');
    } catch (error) {
      flash(error instanceof Error ? error.message : 'The scan could not be completed.');
    } finally { setBusy(false); }
  }

  async function copySafeText() {
    if (!result) return;
    try { await navigator.clipboard.writeText(result.sanitized_text); flash('Redacted copy copied to clipboard.'); }
    catch { flash('Clipboard access is unavailable. Select and copy the sanitized text manually.'); }
  }

  function downloadSafeText() {
    if (!result) return;
    const blob = new Blob([result.sanitized_text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'clearline-sanitized-' + result.id + '.txt';
    anchor.click();
    URL.revokeObjectURL(url);
  }

  if (loading) return <div className="auth-state"><span className="brand-mark clearline-mark">c</span><p>Opening Clearline…</p></div>;

  if (!user) return (
    <main className="clearline-login">
      <div className="clearline-login-card">
        <a className="clearline-brand" href="/"><span className="clearline-logo">c</span><span>clearline<small>DATA PROTECTION</small></span></a>
        <p className="clearline-eyebrow">A SAFER WAY TO SHARE WORK</p>
        <h1>Let sensitive<br /><em>details stay private.</em></h1>
        <p className="clearline-lede">Inspect text before it leaves your workspace. Clearline spots common personal and credential patterns, then gives you a redacted copy.</p>
        {loginError && <p className="clearline-error" role="alert">Sign-in could not be completed. Please try again.</p>}
        <a className="clearline-primary" href={API + '/login'}>Continue with Mini SSO <span>↗</span></a>
        <a className="clearline-back" href="/">← Back to your apps</a>
        <p className="clearline-footnote">DEMO POLICY · RULE-BASED SCANNING · NO ORIGINAL TEXT RETAINED</p>
      </div>
      <div className="clearline-login-art"><div className="shield-illustration"><span>✓</span></div><p>Private by design.<br /><em>Clear before sharing.</em></p></div>
    </main>
  );

  const detectionCount = result?.findings.reduce((sum, item) => sum + item.count, 0) ?? 0;
  const redactedEvents = audit.filter(item => item.action === 'redacted').length;
  const totalFindings = audit.reduce((sum, item) => sum + Object.values(item.findings).reduce((n, count) => n + count, 0), 0);

  return (
    <div className="clearline-app">
      <aside className="clearline-sidebar">
        <a className="clearline-brand" href="/"><span className="clearline-logo">c</span><span>clearline<small>DATA PROTECTION</small></span></a>
        <div className="clearline-workspace"><span className="workspace-dot" /> INTERNAL WORKSPACE <span>⌄</span></div>
        <p className="clearline-nav-label">WORKSPACE</p>
        <button className={'clearline-nav-item ' + (section === 'inspect' ? 'active' : '')} onClick={() => setSection('inspect')}><span>⌕</span> Inspect content</button>
        {isAdmin && <button className={'clearline-nav-item ' + (section === 'audit' ? 'active' : '')} onClick={() => setSection('audit')}><span>▤</span> Audit log <small>ADMIN</small></button>}
        <div className="clearline-sidebar-bottom">
          <div className="clearline-user-avatar">{(user.name[0] ?? 'U').toUpperCase()}</div>
          <div className="clearline-user-copy"><strong>{user.name}</strong><small>{isAdmin ? 'Security administrator' : 'Employee workspace'}</small></div>
          <a className="clearline-logout" href={API + '/logout'} aria-label="Sign out">↗</a>
        </div>
      </aside>

      <main className="clearline-main">
        <header className="clearline-topbar"><div><a href="/">Apps</a><span>/</span><strong>Clearline DLP</strong></div><nav><a href="/app">Daymark <span>↗</span></a><span className="secure-status"><i /> SSO protected</span></nav></header>
        {section === 'inspect' ? (
          <section className="clearline-content">
            <div className="clearline-heading-row"><div><p className="clearline-eyebrow">DATA PROTECTION / EMPLOYEE WORKSPACE</p><h1>Inspect before sharing.</h1><p className="clearline-subtitle">Paste a message or scan a text document. Clearline redacts common sensitive patterns before you use the cleaned copy.</p></div><div className="policy-chip"><span>✳</span> STANDARD POLICY</div></div>
            <div className="scan-layout">
              <section className="scan-card">
                <header className="scan-card-head"><div><p className="scan-card-kicker">NEW INSPECTION</p><h2>What would you like to check?</h2></div><span className="scan-step">01 <i>/</i> 02</span></header>
                {!file ? <label className="scan-input-label">PASTE TEXT <span>{new TextEncoder().encode(text).length.toLocaleString()} / 100,000 bytes</span><textarea value={text} maxLength={MAX_BYTES} onChange={event => { setText(event.target.value); setResult(null); }} placeholder={'Paste a message or document excerpt here…\n\nExample: Please contact me at alex@example.com about the report.'} /></label> : <div className="file-selected"><div className="file-icon">TXT</div><div><strong>{file.name}</strong><span>{(file.size / 1024).toFixed(1)} KB · Ready to scan</span></div><button onClick={() => { setFile(null); setResult(null); }}>Remove</button></div>}
                <div className="scan-input-footer"><div className="drop-zone" onDragOver={event => event.preventDefault()} onDrop={onDrop}><span>↧</span><div><strong>{file ? 'File ready' : 'Or drop a text file here'}</strong><small>TXT, MD, CSV · up to 100 KB</small></div><label className="file-picker">Browse<input type="file" accept=".txt,.md,.csv,text/plain,text/markdown,text/csv" onChange={onFileChange} /></label></div><button className="clearline-primary scan-button" onClick={() => void scan()} disabled={busy || (!file && !text.trim())}>{busy ? <><span className="scan-spinner" /> Scanning…</> : <>Scan content <span>→</span></>}</button></div>
                <div className="privacy-strip"><span>♧</span><p><strong>Privacy first.</strong> The source text is scanned in memory and is not saved. Only the redacted preview is returned; the audit log keeps counts and categories, never document text.</p></div>
              </section>
              <aside className="policy-card"><div className="policy-card-icon">⌑</div><p className="scan-card-kicker">ACTIVE DETECTION RULES</p><h3>Common risk patterns</h3><ul><li><span>01</span> Payment card numbers <i>PCI</i></li><li><span>02</span> Aadhaar numbers <i>PII</i></li><li><span>03</span> Email addresses <i>PII</i></li><li><span>04</span> Indian mobile numbers <i>PII</i></li><li><span>05</span> Passwords and API secrets <i>SECRET</i></li></ul><p className="policy-note">Rule-based detection can miss or incorrectly flag content. Review the cleaned copy before sharing.</p></aside>
            </div>
            {result && <section className={'scan-result ' + result.action} aria-live="polite"><div className="result-top"><div className="result-icon">{result.action === 'redacted' ? '!' : '✓'}</div><div><p className="scan-card-kicker">INSPECTION COMPLETE · #{result.id}</p><h2>{result.action === 'redacted' ? detectionCount + ' sensitive pattern' + (detectionCount === 1 ? '' : 's') + ' redacted' : 'No configured patterns detected'}</h2><p>{result.action === 'redacted' ? 'Review the redacted preview before using it.' : 'The content is unchanged. Rule-based scans cannot guarantee that text is safe to share.'}</p></div><span className={'result-badge ' + result.action}>{result.action === 'redacted' ? 'REDACTED' : 'CLEAR'}</span></div>
              {result.findings.length > 0 && <div className="finding-chips">{result.findings.map(item => <span key={item.type}>{prettyKind(item.type)} <b>{item.count}</b></span>)}</div>}
              <label className="scan-input-label">REDACTED PREVIEW <span>ORIGINAL TEXT NOT STORED</span><textarea readOnly value={result.sanitized_text} rows={Math.min(9, Math.max(4, result.sanitized_text.split('\n').length))} /></label>
              <div className="result-footer"><span>Scanned {localTime(result.created_at)} · source content was not retained</span><div><button className="clearline-quiet-button" onClick={copySafeText}>Copy cleaned copy</button><button className="clearline-primary" onClick={downloadSafeText}>Download .txt <span>↓</span></button></div></div>
            </section>}
            <div className="clearline-bottom-note"><span>✳</span> Clearline checks common patterns; it is a learning demo, not a complete security boundary.</div>
          </section>
        ) : (
          <section className="clearline-content">
            <div className="clearline-heading-row"><div><p className="clearline-eyebrow">DATA PROTECTION / ADMINISTRATION</p><h1>Audit log.</h1><p className="clearline-subtitle">A metadata-only trail of scan attempts. Submitted content is never shown here or retained.</p></div><button className="clearline-refresh" onClick={() => void loadAudit()}>↻ Refresh</button></div>
            <div className="audit-stats"><article><span>RECENT SCANS</span><strong>{audit.length}</strong><small>Last 50 entries</small></article><article><span>REDACTED</span><strong>{redactedEvents}</strong><small>Scans with a match</small></article><article><span>FINDINGS</span><strong>{totalFindings}</strong><small>Matched patterns</small></article><article><span>CONTENT STORED</span><strong>0</strong><small>Metadata only</small></article></div>
            <section className="audit-card"><header><div><p className="scan-card-kicker">WORKSPACE ACTIVITY</p><h2>Scan events</h2></div><span>NEWEST FIRST</span></header>
              {auditLoading ? <div className="audit-empty">Loading audit events…</div> : auditError ? <div className="audit-empty audit-error">{auditError}</div> : !audit.length ? <div className="audit-empty"><span>▤</span><strong>No scans recorded yet</strong><small>Completed employee inspections will appear here.</small></div> : <div className="audit-table-wrap"><table className="audit-table"><thead><tr><th>EMPLOYEE</th><th>SOURCE</th><th>RESULT</th><th>FINDINGS</th><th>TIME</th></tr></thead><tbody>{audit.map(row => { const count = Object.values(row.findings).reduce((sum, value) => sum + value, 0); return <tr key={row.id}><td><span className="audit-avatar">{(row.user[0] ?? 'U').toUpperCase()}</span>{row.user}</td><td><span className="source-pill">{row.source === 'file' ? '↥ File' : '¶ Pasted text'}</span></td><td><span className={'audit-status ' + row.action}>{row.action === 'redacted' ? 'Redacted' : 'Clear'}</span></td><td>{count ? <span className="audit-findings">{count} <small>· {Object.keys(row.findings).map(prettyKind).join(', ')}</small></span> : <span className="no-findings">—</span>}</td><td>{localTime(row.created_at)}</td></tr>; })}</tbody></table></div>}
            </section>
            <p className="audit-privacy-note">Audit records contain employee name, scan time, source type, action, and finding counts. They do not contain submitted text, filenames, IP addresses, or matched values.</p>
          </section>
        )}
      </main>
      {notice && <div className="toast" role="status">{notice}</div>}
    </div>
  );
}