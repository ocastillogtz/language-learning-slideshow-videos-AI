// SubtitlesTab.js — top-level "Subtitles" page.
// Edit every on-screen text overlay's style (dialogue + narrator subtitles, footnote,
// shadowing "repeat" message, preposition-quiz option chips + 3-2-1 countdown) and see
// the change on a sample frame before saving it back to config.ini.
//
// Font size + subtitle bottom-margin are stored PER ORIENTATION (the [vertical]/
// [horizontal] config sections); everything else is shared. The orientation toggle
// controls which of those per-orientation values you're editing and previewing.
const { useState, useEffect, useRef } = React;

// Preview modes → renderer style + which style group they exercise.
const PREVIEW_MODES = [
  { id: "dialogue",  label: "Dialogue subtitle",     style: "dialog",    groups: ["dialogue"] },
  { id: "narration", label: "Narrator / title",      style: "narration", groups: ["narrator"] },
  { id: "footnote",  label: "Subtitle + footnote",   style: "dialog",    groups: ["footnote", "dialogue"] },
  { id: "repeat",    label: "Shadowing “repeat”",    style: "repeat",    groups: ["repeat"] },
  { id: "quiz",      label: "Preposition quiz",      style: "quiz",      groups: ["quiz_options", "countdown"] },
];

function jclone(x) { return JSON.parse(JSON.stringify(x)); }

// ── One style control (number / colour / text) ────────────────────────────────
function StyleField({ field, value, onChange }) {
  const common = { value: value ?? "", onChange: e => onChange(e.target.value) };
  if (field.type === "color") {
    // Native picker only speaks hex; the text box keeps CSS names like "PeachPuff".
    const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test((value || "").trim()) ? value.trim() : "#ffffff";
    return (
      <div className="field">
        <label>{field.label}</label>
        <div style={{ display: "flex", gap: ".4rem", alignItems: "center" }}>
          <span title="current colour" style={{
            width: 22, height: 22, borderRadius: 5, flexShrink: 0,
            border: "1px solid var(--border)", background: value || "transparent",
          }}/>
          <input {...common} style={{ flex: 1 }} spellCheck={false}/>
          <input type="color" value={hex} onChange={e => onChange(e.target.value)}
            title="pick a colour"
            style={{ width: 30, height: 30, padding: 0, background: "none", border: "none", cursor: "pointer" }}/>
        </div>
      </div>
    );
  }
  return (
    <div className="field">
      <label>{field.label}</label>
      <input {...common} type={field.type === "number" ? "number" : "text"}
        step={field.step || (field.type === "number" ? 1 : undefined)} spellCheck={false}/>
    </div>
  );
}

// ── Collapsible group of style controls ───────────────────────────────────────
function StyleGroup({ group, open, onToggle, valsFor, onField }) {
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 10, marginBottom: ".7rem", overflow: "hidden" }}>
      <div onClick={onToggle} style={{
        display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer",
        padding: ".65rem .9rem", background: "var(--s1)", userSelect: "none",
      }}>
        <span style={{ fontSize: ".8rem", fontWeight: 600 }}>{group.label}</span>
        <span className="chevron" style={{ transform: open ? "rotate(90deg)" : "none" }}>▸</span>
      </div>
      {open && (
        <div style={{ padding: ".9rem", display: "grid", gridTemplateColumns: "1fr 1fr", gap: ".7rem" }}>
          {group.fields.map(f => (
            <StyleField key={f.key} field={f} value={valsFor[f.key]} onChange={v => onField(f, v)}/>
          ))}
        </div>
      )}
    </div>
  );
}

function SubtitlesTab() {
  const { toast } = useApp();
  const [schema,   setSchema]   = useState(null);
  const [work,     setWork]     = useState(null);   // {vertical:{k:v}, horizontal:{k:v}}
  const [original, setOriginal] = useState(null);
  const [orient,   setOrient]   = useState("vertical");
  const [openIds,  setOpenIds]  = useState(() => new Set(["dialogue"]));
  const [loadErr,  setLoadErr]  = useState("");
  const [saving,   setSaving]   = useState(false);

  // Profiles ("looks")
  const [profiles, setProfiles] = useState([]);
  const [profSel,  setProfSel]  = useState("");
  const [profName, setProfName] = useState("");
  const [profBusy, setProfBusy] = useState(false);

  // Preview state
  const [mode,     setMode]     = useState("dialogue");
  const [text,     setText]     = useState("Ich habe *unbedingt* keine Zeit mehr!");
  const [footnote, setFootnote] = useState("* KI-generierter Inhalt.");
  const [repeatMsg,setRepeatMsg]= useState("");
  const [qOptions, setQOptions] = useState("auf, vor, über");
  const [qAnswer,  setQAnswer]  = useState("vor");
  const [qPartial, setQPartial] = useState("Ich habe Angst...");
  const [qFull,    setQFull]    = useState("Ich habe Angst *vor* großen Spinnen.");
  const [qReveal,  setQReveal]  = useState(false);
  const [qCount,   setQCount]   = useState(false);
  const [src,      setSrc]      = useState("");
  const [pvErr,    setPvErr]    = useState("");
  const [rendering,setRendering]= useState(false);

  const perOrient = useRef(new Set());   // keys stored per orientation
  const allKeys   = useRef([]);
  const timer     = useRef(null);

  // Load schema + current values once.
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/style/schema");
        const d = await r.json();
        if (d.error) throw new Error(d.error);
        setSchema(d.schema);
        setWork(jclone(d.values));
        setOriginal(jclone(d.values));
        const po = new Set(), all = [];
        d.schema.forEach(g => g.fields.forEach(f => {
          all.push(f.key);
          if (f.per_orientation) po.add(f.key);
        }));
        perOrient.current = po;
        allKeys.current = all;
        loadProfiles();
      } catch (e) { setLoadErr(e.message); }
    })();
  }, []);

  async function loadProfiles() {
    try {
      const r = await fetch("/style/profiles");
      const d = await r.json();
      if (!d.error) setProfiles(d.profiles || []);
    } catch { /* non-fatal */ }
  }

  async function applyProfile() {
    if (!profSel) return;
    setProfBusy(true);
    try {
      const r = await fetch("/style/profiles/apply", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: profSel }),
      });
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error || r.statusText);
      setWork(jclone(d.values));       // config now matches → editor is clean
      setOriginal(jclone(d.values));
      toast("Applied", `Profile “${profSel}” written to config.ini`, "ok");
    } catch (e) { toast("Apply failed", e.message, "err"); }
    finally { setProfBusy(false); }
  }

  async function saveProfile() {
    const name = profName.trim();
    if (!name) { toast("Name required", "Enter a profile name first", "err"); return; }
    setProfBusy(true);
    try {
      const r = await fetch("/style/profiles/save", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, values: work }),
      });
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error || r.statusText);
      setProfName("");
      await loadProfiles();
      setProfSel(d.name);
      toast("Saved", `Profile “${d.name}” ${d.overwritten ? "updated" : "created"}`, "ok");
    } catch (e) { toast("Save failed", e.message, "err"); }
    finally { setProfBusy(false); }
  }

  async function deleteProfile() {
    if (!profSel) return;
    setProfBusy(true);
    try {
      const r = await fetch("/style/profiles/delete", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: profSel }),
      });
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error || r.statusText);
      const gone = profSel;
      setProfSel("");
      await loadProfiles();
      toast("Deleted", `Profile “${gone}” removed`, "ok");
    } catch (e) { toast("Delete failed", e.message, "err"); }
    finally { setProfBusy(false); }
  }

  // When the preview mode changes, open the group(s) it exercises.
  useEffect(() => {
    const m = PREVIEW_MODES.find(x => x.id === mode);
    if (m) setOpenIds(new Set(m.groups));
    if (mode === "repeat" && work && !repeatMsg) setRepeatMsg(work[orient].repeat_text || "Jetzt wiederholen");
  }, [mode]);   // eslint-disable-line

  function setField(field, value) {
    setWork(w => {
      const n = { vertical: { ...w.vertical }, horizontal: { ...w.horizontal } };
      if (perOrient.current.has(field.key)) {
        n[orient][field.key] = value;
      } else {                       // shared → mirror to both orientations
        n.vertical[field.key] = value;
        n.horizontal[field.key] = value;
      }
      return n;
    });
  }

  const changed = (() => {
    if (!work || !original) return {};
    const c = {};
    for (const k of allKeys.current)
      if (work[orient][k] !== original[orient][k]) c[k] = work[orient][k];
    return c;
  })();
  const dirtyCount = Object.keys(changed).length;

  // Debounced live preview.
  useEffect(() => {
    if (!work) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(renderPreview, 350);
    return () => timer.current && clearTimeout(timer.current);
  }, [work, orient, mode, text, footnote, repeatMsg, qOptions, qAnswer, qPartial, qFull, qReveal, qCount]);

  async function renderPreview() {
    if (!work) return;
    const m = PREVIEW_MODES.find(x => x.id === mode);
    const body = {
      format: orient, style: m.style, overrides: work[orient],
      text: (mode === "narration" || mode === "dialogue" || mode === "footnote") ? text : "",
      footnote: mode === "footnote" ? footnote : "",
      repeat_message: mode === "repeat" ? (repeatMsg || "Jetzt wiederholen") : "",
      quiz: mode === "quiz" ? {
        options: qOptions.split(",").map(s => s.trim()).filter(Boolean),
        answer: qAnswer, partial: qPartial, full: qFull, reveal: qReveal, countdown: qCount,
      } : null,
    };
    setRendering(true); setPvErr("");
    try {
      const r = await fetch("/style/preview", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      if (!r.ok) {
        let msg = r.statusText; try { msg = (await r.json()).error || msg; } catch {}
        throw new Error(msg);
      }
      const blob = await r.blob();
      setSrc(prev => { if (prev) URL.revokeObjectURL(prev); return URL.createObjectURL(blob); });
    } catch (e) { setPvErr(e.message); }
    finally { setRendering(false); }
  }

  async function save() {
    if (!dirtyCount) return;
    setSaving(true);
    try {
      const r = await fetch("/style/save", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ orientation: orient, changed }),
      });
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error || r.statusText);
      // Mark saved: current orientation clean; shared keys synced on the other one too.
      setOriginal(o => {
        const other = orient === "vertical" ? "horizontal" : "vertical";
        const n = { vertical: { ...o.vertical }, horizontal: { ...o.horizontal } };
        n[orient] = { ...work[orient] };
        for (const k of allKeys.current)
          if (!perOrient.current.has(k)) n[other][k] = work[other][k];
        return n;
      });
      toast("Saved", `${d.saved} value${d.saved === 1 ? "" : "s"} written to config.ini`, "ok");
    } catch (e) { toast("Save failed", e.message, "err"); }
    finally { setSaving(false); }
  }

  function reset() {
    if (!original) return;
    setWork(jclone(original));
  }

  if (loadErr) return <div className="step-log vis err" style={{ margin: "1rem 0" }}>{loadErr}</div>;
  if (!schema || !work) return <div style={{ color: "var(--muted)", padding: "2rem" }}>Loading styles…</div>;

  const valsFor = work[orient];

  return (
    <div>
      <div className="proj-hdr" style={{ marginBottom: "1.2rem" }}>
        <h1 style={{ fontSize: "1.4rem", margin: 0 }}>Subtitles &amp; Overlays</h1>
        <div className="sub">
          Tune every on-screen text style and preview it on a sample frame
          (<code>assets/samples/{orient}.png</code>). Size &amp; bottom-margin are saved per
          orientation; other values are shared. Changes write to <code>config.ini</code>.
        </div>
      </div>

      {/* Toolbar */}
      <div style={{ display: "flex", gap: ".6rem", alignItems: "center", flexWrap: "wrap", marginBottom: "1.2rem" }}>
        <div style={{ display: "flex", gap: ".25rem", background: "var(--s2)", borderRadius: 8, padding: 3 }}>
          {["vertical", "horizontal"].map(o => (
            <button key={o} className={"btn-ghost" + (orient === o ? " active" : "")}
              onClick={() => setOrient(o)}
              style={{ fontSize: ".78rem", padding: ".35rem .8rem", background: orient === o ? "var(--accent)" : "transparent", color: orient === o ? "#0d0d10" : "var(--muted)", border: "none" }}>
              {o === "vertical" ? "Vertical 1080×1920" : "Horizontal 1920×1080"}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }}/>
        {dirtyCount > 0 && (
          <span style={{ fontSize: ".76rem", color: "var(--accent)" }}>
            {dirtyCount} unsaved change{dirtyCount === 1 ? "" : "s"}
          </span>
        )}
        <button className="btn-cancel" onClick={reset} disabled={dirtyCount === 0}
          style={{ fontSize: ".8rem" }}>Reset</button>
        <button className="btn-primary" onClick={save} disabled={saving || dirtyCount === 0}>
          {saving ? "Saving…" : "Save to config"}
        </button>
      </div>

      {/* Profiles ("looks") */}
      <div style={{
        display: "flex", gap: ".55rem", alignItems: "center", flexWrap: "wrap",
        marginBottom: "1.2rem", padding: ".7rem .9rem",
        border: "1px solid var(--border)", borderRadius: 10, background: "var(--s1)",
      }}>
        <span style={{ fontSize: ".66rem", fontWeight: 600, letterSpacing: ".1em", textTransform: "uppercase", color: "var(--muted)" }}>Profiles</span>
        <select value={profSel} onChange={e => setProfSel(e.target.value)}
          style={{ background: "var(--s2)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text)", fontFamily: "'DM Sans',sans-serif", fontSize: ".82rem", padding: ".4rem .6rem", minWidth: 160 }}>
          <option value="">{profiles.length ? "— select a profile —" : "— none saved yet —"}</option>
          {profiles.map(n => <option key={n} value={n}>{n}</option>)}
        </select>
        <button className="btn-ghost" onClick={applyProfile} disabled={!profSel || profBusy}
          title="Write this profile to config.ini (both orientations) and load it here"
          style={{ fontSize: ".8rem" }}>Apply</button>
        <button className="btn-ghost" onClick={deleteProfile} disabled={!profSel || profBusy}
          style={{ fontSize: ".8rem", color: "#f0857d" }}>Delete</button>
        <div style={{ width: 1, height: 22, background: "var(--border)", margin: "0 .2rem" }}/>
        <input value={profName} onChange={e => setProfName(e.target.value)}
          onKeyDown={e => e.key === "Enter" && saveProfile()}
          placeholder="New profile name…" spellCheck={false}
          style={{ background: "var(--s2)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text)", fontFamily: "'DM Sans',sans-serif", fontSize: ".82rem", padding: ".4rem .6rem", width: 180 }}/>
        <button className="btn-ghost" onClick={saveProfile} disabled={profBusy}
          title="Snapshot the current values (both orientations) as a named profile"
          style={{ fontSize: ".8rem" }}>Save current as</button>
        <span style={{ flex: 1 }}/>
        <span style={{ fontSize: ".72rem", color: "var(--muted)" }}>
          Applying overwrites <code>config.ini</code> — snapshot first to keep your current look.
        </span>
      </div>

      {/* Two columns: editor | live preview */}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(380px, 1fr) minmax(300px, 460px)", gap: "1.6rem", alignItems: "start" }}>
        {/* Editor */}
        <div>
          {schema.map(g => (
            <StyleGroup key={g.id} group={g} open={openIds.has(g.id)}
              onToggle={() => setOpenIds(s => { const n = new Set(s); n.has(g.id) ? n.delete(g.id) : n.add(g.id); return n; })}
              valsFor={valsFor} onField={setField}/>
          ))}
        </div>

        {/* Preview */}
        <div style={{ position: "sticky", top: "1rem" }}>
          <div className="field" style={{ marginBottom: ".7rem" }}>
            <label>Preview mode</label>
            <select value={mode} onChange={e => setMode(e.target.value)}>
              {PREVIEW_MODES.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </div>

          {(mode === "dialogue" || mode === "narration" || mode === "footnote") && (
            <div className="field" style={{ marginBottom: ".6rem" }}>
              <label>Sample text {mode !== "narration" && <span style={{ textTransform: "none", color: "var(--muted)", fontWeight: 300 }}>(*bold* / _underline_ markup ok)</span>}</label>
              <textarea rows={2} value={text} onChange={e => setText(e.target.value)}/>
            </div>
          )}
          {mode === "footnote" && (
            <div className="field" style={{ marginBottom: ".6rem" }}>
              <label>Footnote text</label>
              <input value={footnote} onChange={e => setFootnote(e.target.value)}/>
            </div>
          )}
          {mode === "repeat" && (
            <div className="field" style={{ marginBottom: ".6rem" }}>
              <label>Repeat message</label>
              <input value={repeatMsg} onChange={e => setRepeatMsg(e.target.value)} placeholder="Jetzt wiederholen"/>
            </div>
          )}
          {mode === "quiz" && (
            <div style={{ marginBottom: ".6rem" }}>
              <div className="field" style={{ marginBottom: ".5rem" }}>
                <label>Options (comma-separated)</label>
                <input value={qOptions} onChange={e => setQOptions(e.target.value)}/>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: ".5rem", marginBottom: ".5rem" }}>
                <div className="field"><label>Correct answer</label>
                  <input value={qAnswer} onChange={e => setQAnswer(e.target.value)}/></div>
                <div className="field"><label>Partial sentence</label>
                  <input value={qPartial} onChange={e => setQPartial(e.target.value)}/></div>
              </div>
              <div className="field" style={{ marginBottom: ".5rem" }}>
                <label>Full sentence (*answer* highlighted)</label>
                <input value={qFull} onChange={e => setQFull(e.target.value)}/>
              </div>
              <div style={{ display: "flex", gap: "1.2rem" }}>
                <label className="toggle-row" style={{ display: "flex", gap: ".4rem", alignItems: "center", fontSize: ".8rem", color: "var(--text)", cursor: "pointer" }}>
                  <input type="checkbox" checked={qReveal} onChange={e => setQReveal(e.target.checked)}/> Reveal answer
                </label>
                <label className="toggle-row" style={{ display: "flex", gap: ".4rem", alignItems: "center", fontSize: ".8rem", color: "var(--text)", cursor: "pointer" }}>
                  <input type="checkbox" checked={qCount} onChange={e => setQCount(e.target.checked)}/> Show countdown
                </label>
              </div>
            </div>
          )}

          <div style={{ position: "relative", marginTop: ".4rem", textAlign: "center", background: "#000", borderRadius: 8, border: "1px solid var(--border)", minHeight: 200 }}>
            {src && <img src={src} alt="preview" style={{ maxWidth: "100%", maxHeight: 620, borderRadius: 8 }}/>}
            {rendering && (
              <div style={{ position: "absolute", top: 8, right: 10, fontSize: ".72rem", color: "var(--accent)" }}>rendering…</div>
            )}
          </div>
          {pvErr && <div className="step-log vis err" style={{ marginTop: ".6rem" }}>{pvErr}</div>}
        </div>
      </div>
    </div>
  );
}
