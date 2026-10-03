// App.js
const { useState, useEffect, useRef } = React;

// Header pill showing the active workspace (language + channel); opens a menu to switch.
function WorkspaceSwitcher({ onManage }) {
  const { workspace, workspaces, switchWorkspace } = useApp();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const close = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  if (!workspace) return null;
  return (
    <div className="ws-switch" ref={ref}>
      <button className="ws-pill" onClick={() => setOpen(o => !o)} title="Workspace (language / channel)">
        <Flag code={workspace.language.flag}/>
        <span>{workspace.name}</span>
        <span className="lang-caret">▾</span>
      </button>
      {open && (
        <div className="ws-menu">
          <div className="ws-menu-label">Workspaces</div>
          {workspaces.map(w => (
            <div key={w.slug} className={"ws-menu-item" + (w.slug === workspace.slug ? " sel" : "")}
              onClick={async () => { setOpen(false); if (w.slug !== workspace.slug) await switchWorkspace(w.slug); }}>
              <Flag code={w.language.flag}/>
              <div style={{minWidth:0}}>
                <div>{w.name}</div>
                <small>{w.language.name}{w.channel_name ? ` · ${w.channel_name}` : ""}</small>
              </div>
              {w.slug === workspace.slug && <span className="ws-check">✓</span>}
            </div>
          ))}
          <div className="ws-menu-item ws-menu-manage" onClick={() => { setOpen(false); onManage(); }}>
            Manage workspaces…
          </div>
        </div>
      )}
    </div>
  );
}

const NAV = [
  { id: "projects", label: "Projects" },
  { id: "assets",   label: "Assets"   },
  { id: "settings", label: "Settings" },
];

function App() {
  const { loadAssets, refreshSidebar, loadWorkspaces, workspace } = useApp();
  const [newProjOpen, setNewProjOpen] = useState(false);
  const [view,        setView]        = useState("projects"); // "projects" | "assets" | "settings"
  const [settingsTab, setSettingsTab] = useState("workspace");

  useEffect(() => {
    loadWorkspaces();
    loadAssets();
    refreshSidebar();
  }, []);

  useEffect(() => {
    document.title = workspace ? `${workspace.name} · Language Pipeline` : "Language Pipeline";
  }, [workspace && workspace.name]);

  function openSettings(tab) { setSettingsTab(tab); setView("settings"); }

  return (
    <>
      {/* Header */}
      <header className="hdr">
        <div className="brand">
          {workspace && (workspace.icon_url || workspace.mascot_url) && (
            <img className="brand-icon" src={workspace.icon_url || workspace.mascot_url} alt=""/>
          )}
          <div className="logo">Language<em>.</em>Pipeline</div>
        </div>
        <WorkspaceSwitcher onManage={() => openSettings("workspace")}/>

        <nav className="hdr-nav">
          {NAV.map(n => (
            <button key={n.id} className={"hdr-nav-btn" + (view === n.id ? " active" : "")} onClick={() => setView(n.id)}>
              {n.label}
            </button>
          ))}
        </nav>

        <button className="btn-primary" style={{visibility: view === "projects" ? "visible" : "hidden"}}
          onClick={() => setNewProjOpen(true)}>
          <svg width="13" height="13" viewBox="0 0 13 13"
            stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" fill="none">
            <line x1="6.5" y1="1" x2="6.5" y2="12"/>
            <line x1="1"   y1="6.5" x2="12" y2="6.5"/>
          </svg>
          New Project
        </button>
      </header>

      {/* Layout — workspace-specific views remount when the workspace changes */}
      {view === "projects" ? (
        <div className="shell">
          <Sidebar onNewProject={() => setNewProjOpen(true)}/>
          <main className="main">
            <ProjectView/>
          </main>
        </div>
      ) : (
        <div className="shell" style={{gridTemplateColumns:"1fr"}}>
          <main className="main" key={workspace ? workspace.slug : "none"}>
            {view === "assets"
              ? <AssetsTab onNavigate={(v) => v === "subtitles" ? openSettings("subtitles") : setView(v)}/>
              : <SettingsView tab={settingsTab} onTab={setSettingsTab}/>}
          </main>
        </div>
      )}

      {/* Toast container */}
      <div className="toasts" id="toasts"/>

      {/* Modals */}
      <NewProjectModal
        open={newProjOpen}
        onClose={() => setNewProjOpen(false)}
      />
    </>
  );
}
