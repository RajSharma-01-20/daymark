import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';

const API = import.meta.env.VITE_DAYMARK_URL ?? 'http://localhost:8101';

type View = 'today' | 'inbox' | 'upcoming' | 'all' | 'completed';
type Task = {
  id: number; title: string; notes: string; priority: number; start_date: string | null;
  due_date: string | null; project_id: number | null; project_name: string | null;
  completed: boolean; completed_at: string | null; tags: string[];
};
type Project = { id: number; name: string; color: string };
type User = { name: string };
type Settings = { theme: 'light' | 'dark'; density: 'comfortable' | 'compact'; startView: Exclude<View, 'completed'>; dateFormat: 'friendly' | 'numeric' };

const defaultSettings: Settings = { theme: 'light', density: 'comfortable', startView: 'today', dateFormat: 'friendly' };
const localToday = () => { const now = new Date(); return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10); };
const viewItems: { id: View; label: string; icon: string }[] = [
  { id: 'today', label: 'Today', icon: '◷' },
  { id: 'inbox', label: 'Inbox', icon: '⌑' },
  { id: 'upcoming', label: 'Upcoming', icon: '▦' },
  { id: 'all', label: 'All tasks', icon: '☷' },
  { id: 'completed', label: 'Completed', icon: '✓' },
];
const priorities = ['No priority', 'Low', 'Medium', 'High', 'Urgent'];

async function api<T>(path: string, csrf: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set('Content-Type', 'application/json');
  if (init.method && init.method !== 'GET') headers.set('X-CSRF-Token', csrf);
  const response = await fetch(`${API}${path}`, { ...init, headers, credentials: 'include' });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { const body = await response.json(); message = body.detail ?? message; } catch { /* Keep the safe fallback. */ }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function savedSettings(): Settings {
  try { return { ...defaultSettings, ...JSON.parse(localStorage.getItem('daymark-settings') ?? '{}') }; }
  catch { return defaultSettings; }
}

function dateLabel(dateValue: string | null, format: Settings['dateFormat']) {
  if (!dateValue) return '';
  const value = new Date(`${dateValue}T12:00:00`);
  if (Number.isNaN(value.getTime())) return dateValue;
  return new Intl.DateTimeFormat(undefined, format === 'friendly' ? { month: 'short', day: 'numeric' } : { month: '2-digit', day: '2-digit', year: 'numeric' }).format(value);
}

function priorityLabel(priority: number) {
  if (!priority) return '';
  return priorities[priority] ?? '';
}

function Daymark() {
  const [user, setUser] = useState<User | null>(null);
  const [csrf, setCsrf] = useState('');
  const [authLoading, setAuthLoading] = useState(true);
  const [activeView, setActiveView] = useState<View>(() => savedSettings().startView);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [search, setSearch] = useState('');
  const [priorityFilter, setPriorityFilter] = useState<number | ''>('');
  const [activeProject, setActiveProject] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [pageLoading, setPageLoading] = useState(false);
  const [notice, setNotice] = useState('');
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<Task | null>(null);
  const [projectDialog, setProjectDialog] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [quickTitle, setQuickTitle] = useState('');
  const [settings, setSettings] = useState<Settings>(savedSettings);
  const quickAddRef = useRef<HTMLInputElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const signInError = new URLSearchParams(window.location.search).get('error');

  const flash = (message: string) => { setNotice(message); window.setTimeout(() => setNotice(''), 3200); };

  const loadLists = useCallback(async (token: string) => {
    const projectList = await api<Project[]>('/api/projects', token);
    setProjects(projectList);
    const day = localToday();
    const [today, inbox, upcoming, all, completed] = await Promise.all(
      (['today', 'inbox', 'upcoming', 'all', 'completed'] as View[]).map(view => api<Task[]>(`/api/tasks?view=${view}&today=${day}`, token)),
    );
    setCounts({ today: today.length, inbox: inbox.length, upcoming: upcoming.length, all: all.length, completed: completed.length });
  }, []);

  const loadTasks = useCallback(async () => {
    if (!csrf) return;
    setPageLoading(true);
    try {
      const params = new URLSearchParams({ view: activeView, q: search });
      params.set('today', localToday());
      if (priorityFilter !== '') params.set('priority', String(priorityFilter));
      if (activeProject !== null) params.set('project_id', String(activeProject));
      const result = await api<Task[]>(`/api/tasks?${params}`, csrf);
      setTasks(result);
    } catch (error) { flash(error instanceof Error ? error.message : 'Could not load tasks.'); }
    finally { setPageLoading(false); }
  }, [activeView, activeProject, csrf, priorityFilter, search]);

  useEffect(() => {
    api<{ authenticated: boolean; user?: User; csrf_token?: string }>('/api/me', '')
      .then(async result => {
        if (!result.authenticated || !result.user || !result.csrf_token) return;
        setUser(result.user);
        setCsrf(result.csrf_token);
        await loadLists(result.csrf_token);
      })
      .catch(() => setUser(null))
      .finally(() => setAuthLoading(false));
  }, [loadLists]);

  useEffect(() => { void loadTasks(); }, [loadTasks]);
  useEffect(() => {
    document.documentElement.dataset.theme = settings.theme;
    document.documentElement.dataset.density = settings.density;
    localStorage.setItem('daymark-settings', JSON.stringify(settings));
  }, [settings]);

  useEffect(() => {
    function shortcuts(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing = !!target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);
      if ((event.key.toLowerCase() === 'n' && !typing && !event.metaKey && !event.ctrlKey) || (event.key.toLowerCase() === 'n' && event.altKey)) {
        event.preventDefault(); quickAddRef.current?.focus();
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); searchRef.current?.focus(); }
      if (event.key === 'Escape') { setEditorOpen(false); setProjectDialog(false); setSettingsOpen(false); }
    }
    window.addEventListener('keydown', shortcuts);
    return () => window.removeEventListener('keydown', shortcuts);
  }, []);

  const viewTitle = activeProject !== null ? projects.find(project => project.id === activeProject)?.name ?? 'Project' : viewItems.find(view => view.id === activeView)?.label ?? 'Today';
  const subtitle = useMemo(() => {
    if (activeProject !== null) return 'A little progress adds up.';
    if (activeView === 'today') return new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric' }).format(new Date());
    if (activeView === 'inbox') return 'A quiet place to collect things before you plan them.';
    if (activeView === 'upcoming') return 'See what is waiting around the corner.';
    if (activeView === 'completed') return 'Look at everything you have already moved forward.';
    return 'Everything you are carrying, in one place.';
  }, [activeProject, activeView]);

  async function refresh(token = csrf) {
    if (!token) return;
    await Promise.all([loadTasks(), loadLists(token)]);
  }

  async function quickAdd(event: FormEvent) {
    event.preventDefault();
    if (!quickTitle.trim()) return;
    setBusy(true);
    try {
      await api<Task>('/api/tasks', csrf, { method: 'POST', body: JSON.stringify({ title: quickTitle.trim() }) });
      setQuickTitle('');
      await refresh();
      flash('Task added to your inbox.');
    } catch (error) { flash(error instanceof Error ? error.message : 'Could not add task.'); }
    finally { setBusy(false); }
  }

  async function saveTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = {
      title: String(form.get('title') ?? '').trim(), notes: String(form.get('notes') ?? '').trim(),
      priority: Number(form.get('priority') ?? 0), start_date: String(form.get('start_date') ?? '') || null,
      due_date: String(form.get('due_date') ?? '') || null,
      project_id: String(form.get('project_id') ?? '') ? Number(form.get('project_id')) : null,
      tags: String(form.get('tags') ?? '').split(',').map(tag => tag.trim()).filter(Boolean),
    };
    setBusy(true);
    try {
      if (editing) await api<Task>(`/api/tasks/${editing.id}`, csrf, { method: 'PATCH', body: JSON.stringify(payload) });
      else await api<Task>('/api/tasks', csrf, { method: 'POST', body: JSON.stringify(payload) });
      setEditorOpen(false); setEditing(null); await refresh(); flash(editing ? 'Task updated.' : 'Task created.');
    } catch (error) { flash(error instanceof Error ? error.message : 'Could not save the task.'); }
    finally { setBusy(false); }
  }

  async function toggleTask(task: Task) {
    try {
      await api<Task>(`/api/tasks/${task.id}`, csrf, { method: 'PATCH', body: JSON.stringify({ completed: !task.completed }) });
      await refresh(); flash(task.completed ? 'Task reopened.' : 'Task completed.');
    } catch (error) { flash(error instanceof Error ? error.message : 'Could not update the task.'); }
  }

  async function deleteTask(task: Task) {
    if (!window.confirm(`Delete “${task.title}”? This cannot be undone.`)) return;
    try { await api<void>(`/api/tasks/${task.id}`, csrf, { method: 'DELETE' }); await refresh(); flash('Task deleted.'); }
    catch (error) { flash(error instanceof Error ? error.message : 'Could not delete the task.'); }
  }

  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get('name') ?? '').trim();
    if (!name) return;
    try {
      await api<Project>('/api/projects', csrf, { method: 'POST', body: JSON.stringify({ name, color: String(form.get('color') ?? 'sage') }) });
      setProjectDialog(false); await refresh(); flash(`Project “${name}” created.`);
    } catch (error) { flash(error instanceof Error ? error.message : 'Could not create project.'); }
  }

  if (authLoading) return <div className="auth-state"><span className="brand-mark">d</span><p>Getting Daymark ready…</p></div>;
  if (!user) return (
    <main className="signin-page">
      <div className="signin-paper">
        <a className="wordmark" href="/"><span className="brand-mark">d</span> daymark</a>
        <p className="eyebrow">A CALMER WAY TO GET THINGS DONE</p>
        <h1>Make room for<br /><em>what matters.</em></h1>
        <p className="signin-copy">Collect your tasks, make a thoughtful plan, and move through the day one thing at a time.</p>
        {signInError && <p className="inline-error" role="alert">Sign-in could not be completed. Please try again.</p>}
        <a className="primary-button signin-button" href={`${API}/login`}>Continue with Mini SSO <span>↗</span></a>
        <p className="signin-footnote">Your password stays with Mini SSO.</p>
      </div>
      <div className="signin-side"><div className="side-orbit orbit-1"/><div className="side-orbit orbit-2"/><div className="side-orbit orbit-3"/><div className="side-note"><span>ONE THING AT A TIME</span><strong>Plan with intention.<br/>Finish with ease.</strong><i>DAYMARK · PERSONAL TASKS</i></div></div>
    </main>
  );

  return (
    <div className="daymark-app">
      <aside className="sidebar">
        <div className="sidebar-top"><a className="wordmark" href="/app"><span className="brand-mark">d</span> daymark</a><button className="icon-button mobile-close" aria-label="Close navigation" onClick={() => document.body.classList.remove('nav-open')}>×</button></div>
        <button className="new-task-button" onClick={() => { setEditing(null); setEditorOpen(true); }}><span>＋</span> New task <kbd>N</kbd></button>
        <div className="nav-label">YOUR SPACE</div>
        <nav className="main-nav" aria-label="Task views">
          {viewItems.map(item => <button key={item.id} className={`nav-item ${activeProject === null && activeView === item.id ? 'selected' : ''}`} onClick={() => { setActiveProject(null); setActiveView(item.id); }}><span className="nav-icon">{item.icon}</span><span>{item.label}</span><span className="nav-count">{counts[item.id] ?? 0}</span></button>)}
        </nav>
        <div className="project-heading"><span>PROJECTS</span><button className="tiny-icon-button" aria-label="Add project" onClick={() => setProjectDialog(true)}>＋</button></div>
        <nav className="project-nav" aria-label="Projects">
          {projects.map(project => <button key={project.id} className={`nav-item project-item ${activeProject === project.id ? 'selected' : ''}`} onClick={() => { setActiveProject(project.id); setActiveView('all'); }}><span className={`project-dot color-${project.color}`} /><span className="project-name">{project.name}</span></button>)}
          {!projects.length && <p className="sidebar-hint">Your projects will appear here.</p>}
        </nav>
        <div className="sidebar-bottom"><button className="nav-item settings-link" onClick={() => setSettingsOpen(true)}><span className="nav-icon">⚙</span><span>Preferences</span></button><div className="user-chip"><div className="avatar">{user.name.slice(0, 1).toUpperCase()}</div><div className="user-meta"><strong>{user.name}</strong><span>Personal workspace</span></div><a className="logout-icon" href={`${API}/logout`} aria-label="Sign out">↗</a></div></div>
      </aside>

      <main className="main-panel">
        <header className="app-header"><button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => document.body.classList.add('nav-open')}>☰</button><div className="breadcrumb"><span>MY DAYMARK</span><b>/</b><strong>{viewTitle}</strong></div><div className="header-actions"><label className="search-box"><span>⌕</span><input ref={searchRef} aria-label="Search tasks" placeholder="Search tasks…" value={search} onChange={event => setSearch(event.target.value)} /><kbd>⌘ K</kbd></label><button className="icon-button settings-mobile" aria-label="Preferences" onClick={() => setSettingsOpen(true)}>⚙</button></div></header>
        <section className="content-area">
          <div className="view-heading"><div><p className="view-eyebrow">{activeView === 'today' && activeProject === null ? 'A FRESH PAGE' : 'YOUR TASKS'}</p><h1>{viewTitle}<span className="title-count">{tasks.length}</span></h1><p className="view-subtitle">{subtitle}</p></div><button className="primary-button add-task-top" onClick={() => { setEditing(null); setEditorOpen(true); }}>＋ <span>Add task</span></button></div>
          <form className="quick-add" onSubmit={quickAdd}><span className="quick-plus">＋</span><input ref={quickAddRef} value={quickTitle} onChange={event => setQuickTitle(event.target.value)} placeholder="Add a task to your inbox…" aria-label="Quick add task" /><button disabled={busy || !quickTitle.trim()} type="submit">Add task <span>↵</span></button></form>
          <div className="list-toolbar"><div className="list-context"><span className="context-dot" /> {activeView === 'completed' ? 'A record of your progress' : 'Keep it simple. Start anywhere.'}</div><div className="filters"><label className="filter-select"><span>Priority</span><select aria-label="Filter by priority" value={priorityFilter} onChange={event => setPriorityFilter(event.target.value === '' ? '' : Number(event.target.value))}><option value="">Any</option>{priorities.slice(1).map((label, index) => <option key={label} value={index + 1}>{label}</option>)}</select></label><button className={`filter-clear ${priorityFilter !== '' ? 'visible' : ''}`} onClick={() => setPriorityFilter('')}>Clear</button></div></div>
          <div className="task-list" aria-live="polite">
            {pageLoading ? <div className="list-state"><span className="loader"/>Gathering your tasks…</div> : tasks.length ? tasks.map(task => <article className={`task-row ${task.completed ? 'is-complete' : ''}`} key={task.id}>
              <button className={`task-check ${task.completed ? 'checked' : ''}`} aria-label={task.completed ? `Reopen ${task.title}` : `Complete ${task.title}`} onClick={() => void toggleTask(task)}>{task.completed ? '✓' : ''}</button>
              <button className="task-main" onClick={() => { setEditing(task); setEditorOpen(true); }}><span className="task-title">{task.title}</span>{task.notes && <span className="task-notes">{task.notes}</span>}<span className="task-meta">{task.project_name && <span className="meta-project">{task.project_name}</span>}{task.due_date && <span className={`meta-date ${task.due_date < new Date().toISOString().slice(0,10) && !task.completed ? 'overdue' : ''}`}>◷ {dateLabel(task.due_date, settings.dateFormat)}</span>}{task.tags.map(tag => <span className="tag-chip" key={tag}>#{tag}</span>)}</span></button>
              <span className={`priority-mark priority-${task.priority}`} title={priorityLabel(task.priority)}>{task.priority ? `P${task.priority}` : ''}</span><button className="row-more" aria-label={`More options for ${task.title}`} onClick={() => { setEditing(task); setEditorOpen(true); }}>···</button>
            </article>) : <div className="empty-state"><div className="empty-illustration"><span className="empty-sun"/><span className="empty-page">✓</span><span className="empty-leaf">⌁</span></div><h2>{search || priorityFilter !== '' ? 'No tasks match that view.' : activeView === 'completed' ? 'Your next little win is waiting.' : activeView === 'today' ? 'A little room to breathe.' : activeView === 'inbox' ? 'Your inbox is clear.' : 'Nothing planned here yet.'}</h2><p>{search || priorityFilter !== '' ? 'Try changing your search or clearing the filters.' : 'Add a task above. You can decide when and where it belongs later.'}</p>{!search && <button className="text-button" onClick={() => { setEditing(null); setEditorOpen(true); }}>Create a task <span>↗</span></button>}</div>}
          </div>
          <div className="list-endnote"><span>✳</span> Your pace is a good pace.</div>
        </section>
      </main>

      {notice && <div className="toast" role="status">{notice}</div>}

      {editorOpen && <div className="modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) { setEditorOpen(false); setEditing(null); } }}><section className="task-modal" role="dialog" aria-modal="true" aria-labelledby="task-dialog-title"><header><div><p className="modal-kicker">MAKE IT ACTIONABLE</p><h2 id="task-dialog-title">{editing ? 'Edit task' : 'A new task'}</h2></div><button className="icon-button" aria-label="Close dialog" onClick={() => { setEditorOpen(false); setEditing(null); }}>×</button></header><form onSubmit={saveTask}><label className="field-label">Task title<input autoFocus name="title" required maxLength={200} defaultValue={editing?.title ?? ''} placeholder="What would you like to get done?" /></label><label className="field-label">A few details <span>OPTIONAL</span><textarea name="notes" maxLength={5000} defaultValue={editing?.notes ?? ''} placeholder="Add a note to help future you…" rows={3}/></label><div className="field-grid"><label className="field-label">Start date<input type="date" name="start_date" defaultValue={editing?.start_date ?? ''}/></label><label className="field-label">Due date<input type="date" name="due_date" defaultValue={editing?.due_date ?? ''}/></label><label className="field-label">Priority<select name="priority" defaultValue={editing?.priority ?? 0}>{priorities.map((label, index) => <option key={label} value={index}>{label}</option>)}</select></label><label className="field-label">Project<select name="project_id" defaultValue={editing?.project_id ?? ''}><option value="">No project yet</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label></div><label className="field-label">Tags <span>SEPARATE WITH COMMAS</span><input name="tags" defaultValue={editing?.tags.join(', ') ?? ''} placeholder="work, home, someday" /></label><footer><div>{editing && <button className="delete-button" type="button" onClick={() => { void deleteTask(editing); setEditorOpen(false); }}>Delete task</button>}</div><div className="modal-actions"><button type="button" className="quiet-button" onClick={() => { setEditorOpen(false); setEditing(null); }}>Cancel</button><button type="submit" className="primary-button" disabled={busy}>{busy ? 'Saving…' : editing ? 'Save changes' : 'Create task'}</button></div></footer></form></section></div>}

      {projectDialog && <div className="modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setProjectDialog(false); }}><section className="task-modal small-modal" role="dialog" aria-modal="true" aria-labelledby="project-dialog-title"><header><div><p className="modal-kicker">MAKE SPACE FOR A BIGGER GOAL</p><h2 id="project-dialog-title">New project</h2></div><button className="icon-button" aria-label="Close dialog" onClick={() => setProjectDialog(false)}>×</button></header><form onSubmit={createProject}><label className="field-label">Project name<input name="name" autoFocus required maxLength={80} placeholder="e.g. Spring semester" /></label><label className="field-label">Project color<select name="color"><option value="sage">Sage</option><option value="blue">Blue</option><option value="amber">Amber</option><option value="rose">Rose</option><option value="slate">Slate</option></select></label><footer><span/><div className="modal-actions"><button type="button" className="quiet-button" onClick={() => setProjectDialog(false)}>Cancel</button><button type="submit" className="primary-button">Create project</button></div></footer></form></section></div>}

      {settingsOpen && <div className="modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setSettingsOpen(false); }}><section className="task-modal small-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title"><header><div><p className="modal-kicker">MAKE DAYMARK YOURS</p><h2 id="settings-title">Preferences</h2></div><button className="icon-button" aria-label="Close preferences" onClick={() => setSettingsOpen(false)}>×</button></header><div className="settings-list"><label>Appearance<select value={settings.theme} onChange={event => setSettings({ ...settings, theme: event.target.value as Settings['theme'] })}><option value="light">Light · paper</option><option value="dark">Dark · evening</option></select></label><label>Task list density<select value={settings.density} onChange={event => setSettings({ ...settings, density: event.target.value as Settings['density'] })}><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></label><label>Starting view<select value={settings.startView} onChange={event => { const startView = event.target.value as Settings['startView']; setSettings({ ...settings, startView }); setActiveView(startView); setActiveProject(null); }}>{viewItems.filter(item => item.id !== 'completed').map(item => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label><label>Date style<select value={settings.dateFormat} onChange={event => setSettings({ ...settings, dateFormat: event.target.value as Settings['dateFormat'] })}><option value="friendly">Feb 14</option><option value="numeric">02/14/2026</option></select></label></div></section></div>}
    </div>
  );
}

export default function App() {
  if (window.location.pathname === '/app' || window.location.pathname === '/app/') return <Daymark />;
  return <main className="launch-page"><div className="launch-card"><a className="wordmark" href="/app"><span className="brand-mark">d</span> daymark</a><p className="eyebrow">YOUR PERSONAL TASK SPACE</p><h1>Make room for<br/><em>what matters.</em></h1><p>Gather the small things, make a plan that feels right, and do the next one.</p><a className="primary-button" href="/app">Open Daymark <span>↗</span></a><div className="launch-foot">ONE LOGIN · YOUR TASKS · YOUR PACE</div></div><div className="launch-art"><span className="launch-orbit orbit-1"/><span className="launch-orbit orbit-2"/><span className="launch-orbit orbit-3"/><div className="launch-sticky"><span>today's note</span><strong>start somewhere<br/>small.</strong><i>one thing at a time</i></div></div></main>;
}
