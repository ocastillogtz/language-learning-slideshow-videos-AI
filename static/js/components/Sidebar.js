// Sidebar.js — the workspace's projects, newest first, with search.
const { useState } = React;

// Pipeline progress as four dots: script · audio · images · video.
function ProjSteps({ p }) {
  const steps = [["script", p.has_script], ["audio", p.has_audio], ["images", p.has_images], ["video", p.has_video]];
  return (
    <span className="proj-steps" title={steps.map(([n, ok]) => `${n}: ${ok ? "done" : "—"}`).join("\n")}>
      {steps.map(([n, ok]) => <span key={n} className={"proj-step" + (ok ? " ok" : "")}/>)}
    </span>
  );
}

function Sidebar({ onNewProject }) {
  const { projects, currentProject, setCurrentProject,
          stopAllPolls, reloadManifest } = useApp();
  const [q, setQ] = useState("");

  async function selectProject(name) {
    if (name === currentProject) return;
    stopAllPolls();
    setCurrentProject(name);
    await reloadManifest(name);
  }

  const needle = q.trim().toLowerCase();
  const shown = projects.filter(p => !needle ||
    `${p.name} ${p.title || ""} ${p.project_type_key || ""} ${(p.characters || []).join(" ")}`.toLowerCase().includes(needle));

  return (
    <aside className="sidebar">
      <div className="sb-top">
        <div className="sb-label">Projects <span className="as-count">{projects.length}</span></div>
        <input className="pt-filter" style={{margin:0}} placeholder="Search name, type, character…"
          value={q} onChange={e => setQ(e.target.value)}/>
      </div>
      <div className="proj-list">
        {projects.length === 0 && (
          <div className="sb-empty">
            No projects in this workspace yet.
            <button className="btn-ghost" style={{marginTop:".6rem"}} onClick={onNewProject}>+ New project</button>
          </div>
        )}
        {projects.length > 0 && shown.length === 0 && <div className="sb-empty">No project matches “{q}”.</div>}
        {shown.map(p => {
          const dt = p.created_at ? new Date(p.created_at).toLocaleDateString() : "—";
          return (
            <div
              key={p.name}
              className={"proj-item" + (currentProject === p.name ? " active" : "")}
              onClick={() => selectProject(p.name)}
              title={p.title || p.name}
            >
              <div style={{flex:1,minWidth:0}}>
                <div className="proj-name">{p.name}</div>
                <div className="proj-date">
                  {p.project_type_key && <span className="proj-type">{p.project_type_key.replace(/_/g, " ")}</span>}
                  {dt}
                </div>
              </div>
              <ProjSteps p={p}/>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
