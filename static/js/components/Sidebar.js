// Sidebar.js
function Sidebar({ onNewProject }) {
  const { projects, currentProject, setCurrentProject,
          stopAllPolls, reloadManifest, loadAssets } = useApp();

  async function selectProject(name) {
    if (name === currentProject) return;
    stopAllPolls();
    setCurrentProject(name);
    await reloadManifest(name);
  }

  return (
    <aside className="sidebar">
      <div className="sb-top">
        <div className="sb-label">Projects</div>
      </div>
      <div className="proj-list">
        {projects.length === 0 && (
          <div style={{color:"var(--muted)",fontSize:".82rem",padding:".4rem .5rem"}}>
            No projects yet.
          </div>
        )}
        {projects.map(p => {
          const done = p.has_script && p.has_audio && p.has_images;
          const dt = p.created_at
            ? new Date(p.created_at).toLocaleDateString("de-DE")
            : "—";
          return (
            <div
              key={p.name}
              className={"proj-item" + (currentProject === p.name ? " active" : "")}
              onClick={() => selectProject(p.name)}
            >
              <div className={"proj-dot" + (done ? " done" : "")} />
              <div style={{flex:1,minWidth:0}}>
                <div className="proj-name">{p.name}</div>
                <div className="proj-date">{dt}</div>
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
