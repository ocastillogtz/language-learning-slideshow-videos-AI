// ProjectView.js
const { useState } = React;

function ProjectView() {
  const { currentProject, manifest, reloadManifest, toast } = useApp();
  const [tab, setTab] = useState("pipeline");
  const [checking, setChecking] = useState(false);

  async function checkForUpdates() {
    setChecking(true);
    try {
      const d = await apiPost(`/projects/${currentProject}/reconcile`, {});
      await reloadManifest(currentProject);
      const n = (d.images_added || 0) + (d.audio_added || 0);
      toast(
        n ? "Updated" : "Up to date",
        n ? `Found ${d.images_added || 0} image(s) and ${d.audio_added || 0} audio file(s) on disk.`
          : "Manifest already matches the files on disk.",
        "ok"
      );
    } catch (e) {
      toast("Error", e.message, "err");
    } finally {
      setChecking(false);
    }
  }

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
      <div className="proj-hdr" style={{display:"flex", alignItems:"flex-start", justifyContent:"space-between", gap:"1rem"}}>
        <div>
          <h2>{title}</h2>
          <div className="sub">{loc} · {style} · {level} · {chars}</div>
        </div>
        <button className="btn-ghost" onClick={checkForUpdates} disabled={checking}
          title="Scan the project folder and import any images/audio that were created but not recorded"
          style={{whiteSpace:"nowrap", fontSize:".8rem", padding:".4rem .8rem"}}>
          {checking ? "Checking…" : "⟳ Check for updates"}
        </button>
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
