// ProjectView.js
const { useState } = React;

function ProjectView() {
  const { currentProject, manifest } = useApp();
  const [tab, setTab] = useState("pipeline");

  if (!currentProject) {
    return (
      <div className="empty">
        <svg width="68" height="68" viewBox="0 0 68 68" fill="none" opacity=".18">
          <rect x="7" y="11" width="54" height="46" rx="7"
            stroke="#e2e2ea" strokeWidth="3"/>
          <line x1="18" y1="26" x2="50" y2="26"
            stroke="#e2e2ea" strokeWidth="3" strokeLinecap="round"/>
          <line x1="18" y1="37" x2="36" y2="37"
            stroke="#e2e2ea" strokeWidth="3" strokeLinecap="round"/>
        </svg>
        <h3>No project selected</h3>
        <p>Pick a project from the sidebar or create a new one.</p>
      </div>
    );
  }

  const m    = manifest || {};
  const gen  = m.generation_config  || {};
  const vi   = m.video_info         || {};
  const meta = m.project_metadata   || {};

  const title = vi.title || m.title || currentProject;
  const loc   = gen.location_key  || m["location-key"] || "–";
  const style = meta.project_type_key || m.style || "–";
  const level = gen.level || "–";
  const chars = (gen.characters  || []).join(" & ") ||
                (m.characters || []).map(c => c.name || c).join(" & ") || "–";

  return (
    <div>
      <div className="proj-hdr">
        <h2>{title}</h2>
        <div className="sub">{loc} · {style} · {level} · {chars}</div>
      </div>

      <div className="tabs">
        {[
          { id: "pipeline", label: "Pipeline"        },
          { id: "items",    label: "Generated Items"  },
          { id: "manifest", label: "Manifest"         },
        ].map(t => (
          <button
            key={t.id}
            className={"tab" + (tab === t.id ? " active" : "")}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "pipeline" && <PipelineTab projectName={currentProject}/>}
      {tab === "items"    && <ItemsTab    projectName={currentProject}/>}
      {tab === "manifest" && <ManifestTab/>}
    </div>
  );
}
