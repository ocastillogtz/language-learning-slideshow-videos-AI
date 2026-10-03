// Modals.js
const { useState, useEffect } = React;

// Project types come from the active workspace (Settings → Project types), so a
// type added or edited there shows up here and in the Script step.
const TYPE_LABELS = {
  shadowing: "Shadowing (with repetitions)", story: "Story (no repetitions)",
  word_learning: "Word Learning (vocabulary)", register_phrases: "Register Phrases (formal / slang / ...)",
  grammar_pairs: "Grammar Pairs (base → transformed)", song_quiz: "Song Quiz (guess the song)",
  preposition_quiz: "Preposition Quiz", blank_quiz: "Fill-in-the-blank Quiz",
  reading_together: "Reading Together (story → parts + long video)",
  promotional: "Promotional (character speaks → IG story)", song: "Song (audio file → lyric video)",
  podcast: "Podcast (episode + vertical Shorts)",
};
// Types with their own creation flow (Build step) instead of a generated script.
const SPECIAL_TYPES = ["reading_together", "promotional", "song"];

function typeLabel(key, t) {
  if (TYPE_LABELS[key]) return TYPE_LABELS[key];
  if (t && t.base_type && TYPE_LABELS[t.base_type]) return TYPE_LABELS[t.base_type].replace(/ \(/, " — Long (");
  return key.replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
}

function useProjectTypes(active = true) {
  const [types, setTypes] = useState(null);
  useEffect(() => {
    if (!active) return;
    fetch("/settings/project-types").then(r => r.json()).then(d => setTypes(d.types || {})).catch(() => setTypes({}));
  }, [active]);
  return types;
}

// <optgroup>s for a project-type <select>: Vertical / Horizontal (+ special flows).
function ProjectTypeOptions({ types: loaded, current, includeSpecial }) {
  const types = loaded || {};
  const keys = Object.keys(types);
  if (current && !keys.includes(current)) keys.push(current);   // never hide the project's own type
  const groups = [
    ["▸ Vertical — 1080×1920 (Shorts / Reels)", k => !SPECIAL_TYPES.includes(k) && (types[k] || {}).format !== "horizontal"],
    ["▸ Horizontal — 1920×1080 Full HD (YouTube)", k => !SPECIAL_TYPES.includes(k) && (types[k] || {}).format === "horizontal"],
  ];
  if (includeSpecial) groups.push(["▸ Special flows — built in their own step", k => SPECIAL_TYPES.includes(k)]);
  return groups.map(([label, test]) => {
    const ks = keys.filter(test).sort((x, y) => typeLabel(x, types[x]).localeCompare(typeLabel(y, types[y])));
    if (!ks.length) return null;
    return (
      <optgroup key={label} label={label}>
        {ks.map(k => <option key={k} value={k}>{typeLabel(k, types[k])}</option>)}
      </optgroup>
    );
  });
}

const LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"];

function NewProjectModal({ open, onClose }) {
  const { toast, refreshSidebar, setCurrentProject, reloadManifest } = useApp();
  const types = useProjectTypes(open);
  const [name,     setName]     = useState("");
  const [projType, setProjType] = useState("shadowing");
  const [level,    setLevel]    = useState("B1");
  const [context,  setContext]  = useState("");
  const [learning, setLearning] = useState("");
  const [visualGuidelines, setVisualGuidelines] = useState("");
  const [err,      setErr]      = useState("");
  const [saving,   setSaving]   = useState(false);

  const curType        = (types || {})[projType] || {};
  const isWordLearning = (curType.base_type || projType) === "word_learning";
  const isHorizontal   = curType.format === "horizontal";
  const isReading      = projType === "reading_together";
  const isPromotional  = projType === "promotional";
  const isSong         = projType === "song";

  async function save() {
    setErr("");
    // Promotional projects gather their inputs (character, situation, text) in the
    // Build step, so the scene description here is optional.
    if (!name.trim() || (!context.trim() && !isPromotional && !isSong)) {
      setErr((isPromotional || isSong)
        ? "Project name is required."
        : "Project name and scene description are required."); return;
    }
    if (isWordLearning && !learning.trim()) {
      setErr("Word Learning projects require a list of words to teach."); return;
    }
    setSaving(true);
    try {
      await apiPost("/create_project", {
        project_name:      name.trim().replace(/ /g, "_"),
        project_type_key:  projType,
        level:             level,
        context:           context.trim(),
        learning_points:   learning.trim(),
        visual_guidelines: visualGuidelines.trim(),
      });
      const safeName = name.trim().replace(/ /g, "_");
      toast("Created!", `Project "${safeName}" created.`, "ok");
      setName(""); setContext(""); setLearning(""); setVisualGuidelines("");
      setProjType("shadowing"); setLevel("B1");
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
                  : isSong
                  ? <span style={{fontSize:"0.72rem",fontWeight:600,padding:"1px 7px",borderRadius:10,background:"var(--purple,#8b5cf6)",color:"#fff",letterSpacing:"0.03em"}}>Song</span>
                  : isHorizontal
                  ? <span style={{fontSize:"0.72rem",fontWeight:600,padding:"1px 7px",borderRadius:10,background:"var(--accent,#3b82f6)",color:"#fff",letterSpacing:"0.03em"}}>HD 16:9</span>
                  : <span style={{fontSize:"0.72rem",fontWeight:600,padding:"1px 7px",borderRadius:10,background:"var(--muted-bg,#e5e7eb)",color:"var(--muted,#6b7280)",letterSpacing:"0.03em"}}>9:16 Short</span>
                }
              </label>
              <select value={projType} onChange={e=>setProjType(e.target.value)}>
                <ProjectTypeOptions types={types} current={projType} includeSpecial/>
              </select>
              {curType.self_description && (
                <span style={{fontSize:"0.78rem",color:"var(--muted)",lineHeight:1.45}}>{curType.self_description}</span>
              )}
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
              : isSong ? "What the song is about (optional)"
              : "Scene Description"}</label>
            <textarea rows={isReading ? 10 : 4} value={context} onChange={e=>setContext(e.target.value)}
              placeholder={isReading
                ? "Paste the full story here. Old spelling is fine — it will be modernized and split into sentences."
                : isPromotional
                ? "Optional note. You'll pick the character, image situation, and the exact line in the Build step."
                : isSong
                ? "Optional note. You'll pick the audio file (and costume) in the Build Song Source step."
                : projType === "podcast"
                ? "Episode topic, e.g. How to order at a bakery — polite phrases, what to say when you don't know the name of a pastry…"
                : "Describe the scene setting and topic…"}/>
          </div>
          {!isReading && !isPromotional && !isSong && <div className="field">
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
          {!isReading && !isPromotional && <div className="field">
            <label>
              Visual Guidelines
              <span style={{color:"var(--muted)",fontWeight:300}}> (optional)</span>
            </label>
            <textarea rows={3} value={visualGuidelines} onChange={e=>setVisualGuidelines(e.target.value)}
              placeholder={isSong
                ? "Performer costume + setting, kept consistent across every image. Blank = Amir as a rapper (hoodie, backwards snapback, gold chains, sunglasses; neon studio)."
                : "Setting, character clothing/props, and mood/style — applied to every scene. e.g. a cozy local bakery; both wear white aprons, gloves and hair nets; warm morning light."}/>
            <span style={{fontSize:"0.78rem",color:"var(--muted)"}}>
              {isSong
                ? "Art-directs every song image. You can also change it later in the Build Song Source step."
                : "Used to art-direct every image. With this set you don't need a pre-made location."}
            </span>
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
