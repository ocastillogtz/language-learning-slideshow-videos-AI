// Modals.js
const { useState } = React;

const NEW_PROJ_TYPES = {
  vertical: [
    { value: "shadowing",        label: "Shadowing (with repetitions)"            },
    { value: "story",            label: "Story (no repetitions)"                  },
    { value: "word_learning",    label: "Word Learning (vocabulary)"              },
    { value: "register_phrases", label: "Register Phrases (formal / slang / ...)" },
    { value: "grammar_pairs",    label: "Grammar Pairs (base → transformed)"      },
  ],
  horizontal: [
    { value: "shadowing_long",        label: "Shadowing — Long (with repetitions)"            },
    { value: "story_long",            label: "Story — Long (no repetitions)"                  },
    { value: "word_learning_long",    label: "Word Learning — Long (vocabulary)"              },
    { value: "register_phrases_long", label: "Register Phrases — Long (formal / slang / ...)" },
    { value: "grammar_pairs_long",    label: "Grammar Pairs — Long (base → transformed)"      },
  ],
  reading: [
    { value: "reading_together", label: "Reading Together (story → annotated parts + long)" },
  ],
  promotional: [
    { value: "promotional", label: "Promotional (character speaks → IG story)" },
  ],
};

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

  const isWordLearning = projType === "word_learning" || projType === "word_learning_long";
  const isHorizontal   = projType.endsWith("_long");
  const isReading      = projType === "reading_together";
  const isPromotional  = projType === "promotional";

  async function save() {
    setErr("");
    // Promotional projects gather their inputs (character, situation, text) in the
    // Build step, so the scene description here is optional.
    if (!name.trim() || (!context.trim() && !isPromotional)) {
      setErr(isPromotional
        ? "Project name is required."
        : "Project name and scene description are required."); return;
    }
    if (isWordLearning && !learning.trim()) {
      setErr("Word Learning projects require a list of words to teach."); return;
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
              <label style={{display:"flex", alignItems:"center", gap:6}}>
                Project Type
                {isReading
                  ? <span style={{fontSize:"0.72rem",fontWeight:600,padding:"1px 7px",borderRadius:10,background:"var(--green,#10b981)",color:"#fff",letterSpacing:"0.03em"}}>Reading</span>
                  : isPromotional
                  ? <span style={{fontSize:"0.72rem",fontWeight:600,padding:"1px 7px",borderRadius:10,background:"var(--pink,#ec4899)",color:"#fff",letterSpacing:"0.03em"}}>Promo</span>
                  : isHorizontal
                  ? <span style={{fontSize:"0.72rem",fontWeight:600,padding:"1px 7px",borderRadius:10,background:"var(--accent,#3b82f6)",color:"#fff",letterSpacing:"0.03em"}}>HD 16:9</span>
                  : <span style={{fontSize:"0.72rem",fontWeight:600,padding:"1px 7px",borderRadius:10,background:"var(--muted-bg,#e5e7eb)",color:"var(--muted,#6b7280)",letterSpacing:"0.03em"}}>9:16 Short</span>
                }
              </label>
              <select value={projType} onChange={e=>setProjType(e.target.value)}>
                <optgroup label="▸ Vertical — 1080×1920 (Shorts / Reels)">
                  {NEW_PROJ_TYPES.vertical.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                </optgroup>
                <optgroup label="▸ Horizontal — 1920×1080 Full HD (YouTube)">
                  {NEW_PROJ_TYPES.horizontal.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                </optgroup>
                <optgroup label="▸ Reading — story → vertical parts + horizontal long">
                  {NEW_PROJ_TYPES.reading.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                </optgroup>
                <optgroup label="▸ Promotional — single image, character speaks (IG story)">
                  {NEW_PROJ_TYPES.promotional.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                </optgroup>
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
            <label>{isReading ? "Story text (paste a public-domain story)"
              : isPromotional ? "What the video is about (optional)"
              : "Scene Description"}</label>
            <textarea rows={isReading ? 10 : 4} value={context} onChange={e=>setContext(e.target.value)}
              placeholder={isReading
                ? "Paste the full story here. Old spelling is fine — it will be modernized and split into sentences."
                : isPromotional
                ? "Optional note. You'll pick the character, image situation, and the exact line in the Build step."
                : "Describe the scene setting and topic…"}/>
          </div>
          {!isReading && !isPromotional && <div className="field">
            <label>
              {isWordLearning ? "Words to Teach" : "Learning Points"}
              {!isWordLearning && <span style={{color:"var(--muted)",fontWeight:300}}> (optional)</span>}
              {isWordLearning  && <span style={{color:"var(--accent-red,#c0392b)",fontWeight:400,marginLeft:4}}>*</span>}
            </label>
            <textarea rows={3} value={learning} onChange={e=>setLearning(e.target.value)}
              placeholder={isWordLearning
                ? "Comma-separated words, e.g.: schwimmen, kochen, laufen, tanzen"
                : "What language points or vocabulary should be covered?"}/>
            {isWordLearning && (
              <span style={{fontSize:"0.78rem",color:"var(--muted)"}}>
                One word per entry, comma-separated. The video will cover them in this order.
              </span>
            )}
          </div>}
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
