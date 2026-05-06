// Modals.js
const { useState } = React;

const NEW_PROJ_TYPES = [
  { value: "shadowing",        label: "Shadowing (with repetitions)"             },
  { value: "story",            label: "Story (no repetitions)"                   },
  { value: "word_learning",    label: "Word Learning (vocabulary)"               },
  { value: "register_phrases", label: "Register Phrases (formal / slang / ...)"  },
  { value: "grammar_pairs",   label: "Grammar Pairs (base → transformed)"      },
];

const LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"];

function NewProjectModal({ open, onClose }) {
  const { toast, refreshSidebar, setCurrentProject, reloadManifest } = useApp();
  const [name,     setName]     = useState("");
  const [projType, setProjType] = useState("shadowing");
  const [level,    setLevel]    = useState("B1");
  const [context,  setContext]  = useState("");
  const [learning, setLearning] = useState("");
  const [err,      setErr]      = useState("");
  const [saving,   setSaving]   = useState(false);

  async function save() {
    setErr("");
    if (!name.trim() || !context.trim()) {
      setErr("Project name and scene description are required."); return;
    }
    setSaving(true);
    try {
      await apiPost("/create_project", {
        project_name:     name.trim().replace(/ /g, "_"),
        project_type_key: projType,
        level:            level,
        context:          context.trim(),
        learning_points:  learning.trim(),
      });
      const safeName = name.trim().replace(/ /g, "_");
      toast("Created!", `Project "${safeName}" created.`, "ok");
      setName(""); setContext(""); setLearning(""); setProjType("shadowing"); setLevel("B1");
      onClose();
      await refreshSidebar();
      setCurrentProject(safeName);
      await reloadManifest(safeName);
    } catch(e) { setErr(e.message); }
    finally { setSaving(false); }
  }

  if (!open) return null;
  return (
    <div className="modal-bg open" onClick={e => e.target===e.currentTarget && onClose()}>
      <div className="modal-box">
        <div className="modal-hdr">
          <h3>New Project</h3>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="field">
            <label>Project Name</label>
            <input value={name} onChange={e=>setName(e.target.value)} placeholder="e.g. cafe_talk_b1"/>
          </div>
          <div className="field-row">
            <div className="field" style={{flex:2}}>
              <label>Project Type</label>
              <select value={projType} onChange={e=>setProjType(e.target.value)}>
                {NEW_PROJ_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>
            <div className="field" style={{flex:1}}>
              <label>Language Level</label>
              <select value={level} onChange={e=>setLevel(e.target.value)}>
                {LEVELS.map(l => <option key={l} value={l}>{l}</option>)}
              </select>
            </div>
          </div>
          <div className="field">
            <label>Scene Description</label>
            <textarea rows={4} value={context} onChange={e=>setContext(e.target.value)}
              placeholder="Describe the scene setting and topic…"/>
          </div>
          <div className="field">
            <label>Learning Points <span style={{color:"var(--muted)",fontWeight:300}}>(optional)</span></label>
            <textarea rows={3} value={learning} onChange={e=>setLearning(e.target.value)}
              placeholder="What language points or vocabulary should be covered?"/>
          </div>
          {err && <div className="err-msg" style={{display:"block"}}>{err}</div>}
        </div>
        <div className="modal-footer">
          <button className="btn-cancel" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={save} disabled={saving}>
            {saving ? "Creating…" : "Create Project"}
          </button>
        </div>
      </div>
    </div>
  );
}
