// App.js
const { useState, useEffect } = React;

function App() {
  const { loadAssets, refreshSidebar } = useApp();
  const [newProjOpen, setNewProjOpen] = useState(false);
  const [view,        setView]        = useState("projects"); // "projects" | "assets" | "subtitles" | "connections"

  useEffect(() => {
    loadAssets();
    refreshSidebar();
  }, []);

  const isAssets      = view === "assets";
  const isSubtitles   = view === "subtitles";
  const isConnections = view === "connections";
  const isProjects    = view === "projects";
  const isFullWidth   = isAssets || isSubtitles || isConnections;

  return (
    <>
      {/* Header */}
      <header className="hdr">
        <div className="logo">Deutsch<em>.</em>Pipeline</div>

        {/* Nav toggle */}
        <div style={{display:"flex",gap:".35rem",marginLeft:"auto",marginRight:".75rem"}}>
          <button
            className={"btn-ghost" + (isProjects ? " active" : "")}
            style={{fontSize:".8rem",padding:".3rem .75rem"}}
            onClick={() => setView("projects")}>
            Projects
          </button>
          <button
            className={"btn-ghost" + (isAssets ? " active" : "")}
            style={{fontSize:".8rem",padding:".3rem .75rem"}}
            onClick={() => setView("assets")}>
            Assets
          </button>
          <button
            className={"btn-ghost" + (isSubtitles ? " active" : "")}
            style={{fontSize:".8rem",padding:".3rem .75rem"}}
            onClick={() => setView("subtitles")}>
            Subtitles
          </button>
          <button
            className={"btn-ghost" + (isConnections ? " active" : "")}
            style={{fontSize:".8rem",padding:".3rem .75rem"}}
            onClick={() => setView("connections")}>
            Connections
          </button>
        </div>

        {isProjects && (
          <button className="btn-primary" onClick={() => setNewProjOpen(true)}>
            <svg width="13" height="13" viewBox="0 0 13 13"
              stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" fill="none">
              <line x1="6.5" y1="1" x2="6.5" y2="12"/>
              <line x1="1"   y1="6.5" x2="12" y2="6.5"/>
            </svg>
            New Project
          </button>
        )}
      </header>

      {/* Layout */}
      {isFullWidth ? (
        <div className="shell" style={{gridTemplateColumns:"1fr"}}>
          <main className="main">
            {isAssets ? <AssetsTab onNavigate={setView}/> : isSubtitles ? <SubtitlesTab/> : <ConnectionsTab/>}
          </main>
        </div>
      ) : (
        <div className="shell">
          <Sidebar onNewProject={() => setNewProjOpen(true)}/>
          <main className="main">
            <ProjectView/>
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
