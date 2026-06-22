// ItemsTab.js  — displays scenes[] from the new manifest schema
const { useState, useEffect } = React;

// ── URL helpers ────────────────────────────────────────────────────────────────

function sceneImgSrc(projectName, filePath, version) {
  return `/project-files/${projectName}/${filePath}?v=${version || Date.now()}`;
}

function sceneAudioSrc(projectName, filePath) {
  return `/project-files/${projectName}/${filePath}`;
}

// ── Per-scene audio regen button ───────────────────────────────────────────────

function AudioRegenBtn({ projectName, sceneId, onDone }) {
  const { toast, startPoll, reloadManifest } = useApp();
  const [running, setRunning] = useState(false);
  const [log,     setLog]     = useState("");

  async function regen() {
    setRunning(true); setLog("");
    try {
      const d = await apiPost(`/projects/${projectName}/run/audio_scene`, {
        scene_id: sceneId,
      });
      const stepKey = d.step_key || `audio_${sceneId}`;
      startPoll(projectName, stepKey, async (s) => {
        setRunning(false);
        setLog(s.log || "");
        if (s.status === "done") {
          toast("Done", "Audio regenerated.", "ok");
          const m = await reloadManifest(projectName);
          onDone && onDone(m);
        } else if (s.status === "error") {
          toast("Error", s.log, "err");
        }
      });
    } catch(e) {
      setRunning(false); setLog(e.message);
      toast("Error", e.message, "err");
    }
  }

  return (
    <div>
      <button className="btn-ghost" onClick={regen} disabled={running}
        style={{fontSize:".8rem", padding:".4rem .9rem"}}>
        ⟳ Re-generate Audio
        {running && <div className="spin" style={{display:"block", borderTopColor:"var(--muted)"}}/>}
      </button>
      {log && (
        <div className={`step-log vis${log.toLowerCase().includes("error") ? " err" : ""}`}
          style={{marginTop:".4rem", fontSize:".74rem"}}>{log}</div>
      )}
    </div>
  );
}

// ── Grammar annotation viewer / editor ─────────────────────────────────────────

function Chip({ label, title, onRemove }) {
  return (
    <span title={title} style={{display:"inline-flex", alignItems:"center", gap:".3rem",
      fontSize:".72rem", padding:".12rem .45rem", borderRadius:"5px",
      background:"var(--surface-2)", border:"1px solid var(--border)", color:"var(--fg)"}}>
      {label}
      {onRemove && (
        <span onClick={onRemove} title="Remove" role="button"
          style={{cursor:"pointer", color:"var(--muted)", fontWeight:700, lineHeight:1}}>×</span>
      )}
    </span>
  );
}

function AnnotationPanel({ projectName, sceneId }) {
  const { toast } = useApp();
  const [open,    setOpen]    = useState(false);
  const [state,   setState]   = useState(null);   // {exists, annotatable, text}
  const [tokens,  setTokens]  = useState([]);
  const [spans,   setSpans]   = useState([]);
  const [loading, setLoading] = useState(false);
  const [busy,    setBusy]    = useState(false);
  const [dirty,   setDirty]   = useState(false);

  async function load() {
    setLoading(true);
    try {
      const d = await fetch(`/projects/${projectName}/annotations/${sceneId}`).then(r => r.json());
      if (d.error) throw new Error(d.error);
      setState(d); setTokens(d.tokens || []); setSpans(d.spans || []); setDirty(false);
    } catch (e) { toast("Error", e.message, "err"); }
    finally { setLoading(false); }
  }
  function toggle() { const n = !open; setOpen(n); if (n && state === null) load(); }

  function removeAttr(i, key) {
    setTokens(ts => ts.map((t, idx) => {
      if (idx !== i) return t;
      const c = { ...t }; delete c[key];
      if (key === "case") delete c.gender;   // gender only meaningful with a case
      return c;
    }));
    setDirty(true);
  }
  function removeSpan(si) { setSpans(ss => ss.filter((_, idx) => idx !== si)); setDirty(true); }

  async function save() {
    setBusy(true);
    try {
      const d = await apiPost(`/projects/${projectName}/annotations/${sceneId}`, { tokens, spans });
      setState(d); setTokens(d.tokens || []); setSpans(d.spans || []); setDirty(false);
      toast("Saved", "Annotation updated — re-render this scene's clips to apply.", "ok");
    } catch (e) { toast("Error", e.message, "err"); }
    finally { setBusy(false); }
  }
  async function regenerate() {
    setBusy(true);
    try {
      const d = await apiPost(`/projects/${projectName}/annotations/${sceneId}`, { regenerate: true });
      setState(d); setTokens(d.tokens || []); setSpans(d.spans || []); setDirty(false);
      toast("Regenerated", "Fresh annotation from OpenAI — re-render to apply.", "ok");
    } catch (e) { toast("Error", e.message, "err"); }
    finally { setBusy(false); }
  }

  return (
    <div style={{marginTop:".8rem", borderTop:"1px solid var(--border)", paddingTop:".6rem"}}>
      <div onClick={toggle} style={{display:"flex", alignItems:"center", gap:".4rem",
        cursor:"pointer", fontSize:".8rem", fontWeight:600, color:"var(--fg)"}}>
        <span>{open ? "▾" : "▸"}</span> Grammar annotation
        <span style={{fontWeight:400, color:"var(--muted)", fontSize:".74rem"}}>
          (view &amp; edit — remove what you don’t want)
        </span>
      </div>

      {open && (
        <div style={{marginTop:".5rem"}}>
          {loading && <div style={{fontSize:".78rem", color:"var(--muted)"}}>Loading…</div>}

          {!loading && state && !state.annotatable && (
            <div style={{fontSize:".78rem", color:"var(--muted)"}}>
              This scene isn’t grammar-annotated (narration/repetition or non-dialogue).
            </div>
          )}

          {!loading && state && state.annotatable && !state.exists && (
            <div style={{fontSize:".78rem", color:"var(--muted)"}}>
              No annotation cached for this sentence yet.
              <div style={{marginTop:".5rem"}}>
                <button className="btn-ghost" onClick={regenerate} disabled={busy}
                  style={{fontSize:".8rem"}}>
                  {busy ? "Generating…" : "✨ Generate annotation (OpenAI)"}
                </button>
              </div>
            </div>
          )}

          {!loading && state && state.exists && (
            <>
              <div style={{display:"flex", flexDirection:"column"}}>
                {tokens.map((t, i) => (
                  <div key={i} style={{display:"flex", alignItems:"center", gap:".4rem",
                    flexWrap:"wrap", padding:".22rem 0", borderBottom:"1px solid var(--border)"}}>
                    <span style={{minWidth:"7.5rem", fontWeight:600}}>{t.text}</span>
                    {t.case && <Chip label={`${t.case}${t.gender ? " · " + t.gender : ""}`}
                      title="case · gender" onRemove={() => removeAttr(i, "case")}/>}
                    {t.role && <Chip label={t.role} title="role" onRemove={() => removeAttr(i, "role")}/>}
                    {t.tense && <Chip label={t.tense} title="tense" onRemove={() => removeAttr(i, "tense")}/>}
                    {t.infinitive && <Chip label={"→ " + t.infinitive} title="infinitive"
                      onRemove={() => removeAttr(i, "infinitive")}/>}
                    {t.group_id && <Chip label={"grp " + t.group_id} title="separable-verb group"
                      onRemove={() => removeAttr(i, "group_id")}/>}
                  </div>
                ))}
              </div>

              {spans.length > 0 && (
                <div style={{marginTop:".5rem"}}>
                  <div style={{fontSize:".74rem", color:"var(--muted)", marginBottom:".25rem"}}>
                    Subordinate-clause boxes
                  </div>
                  <div style={{display:"flex", flexWrap:"wrap", gap:".4rem"}}>
                    {spans.map((s, si) => {
                      const words = (s.token_ids || []).map(id => tokens[id]?.text).filter(Boolean).join(" ");
                      return <Chip key={si} label={`${(s.type || "").toUpperCase()}: ${words}`}
                        title="Nebensatz box" onRemove={() => removeSpan(si)}/>;
                    })}
                  </div>
                </div>
              )}

              <div className="run-row" style={{marginTop:".7rem", gap:".5rem", flexWrap:"wrap"}}>
                <button className="btn-primary" onClick={save} disabled={busy || !dirty}
                  style={{fontSize:".8rem"}}>
                  {busy ? "Saving…" : "Save annotation"}
                </button>
                <button className="btn-ghost" onClick={regenerate} disabled={busy}
                  style={{fontSize:".8rem"}}
                  title="Discard edits and re-prompt OpenAI for a fresh annotation">
                  ↻ Regenerate (OpenAI)
                </button>
                {dirty && <span style={{fontSize:".74rem", color:"var(--muted)", alignSelf:"center"}}>
                  unsaved changes
                </span>}
              </div>
              <div style={{fontSize:".72rem", color:"var(--muted)", marginTop:".4rem", fontStyle:"italic"}}>
                Edits are cached (no OpenAI call) and applied on the next render of this scene’s clips.
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Per-scene image regen button ───────────────────────────────────────────────

function ImageRegenBtn({ projectName, sceneId, promptId, useLocationRef, charactersMode, cast, onDone }) {
  const { toast, startPoll, reloadManifest } = useApp();
  const [running, setRunning] = useState(false);
  const [log,     setLog]     = useState("");

  async function regen() {
    const promptEl      = document.getElementById(promptId);
    const promptOverride = promptEl?.value.trim() || null;
    setRunning(true); setLog("");
    try {
      const body = {
        scene_id:            sceneId,
        prompt_override:     promptOverride,
        use_location_ref:    useLocationRef,
        characters_override: charactersMode,
      };
      if (cast != null) body.cast = cast;   // reading scenes: explicit character selection
      const d = await apiPost(`/projects/${projectName}/run/image_scene`, body);
      const stepKey = d.step_key || `image_${sceneId}`;
      startPoll(projectName, stepKey, async (s) => {
        setRunning(false);
        setLog(s.log || "");
        if (s.status === "done") {
          toast("Done", "Image regenerated.", "ok");
          const m = await reloadManifest(projectName);
          onDone && onDone(m);
        } else if (s.status === "error") {
          toast("Error", s.log, "err");
        }
      });
    } catch(e) {
      setRunning(false); setLog(e.message);
      toast("Error", e.message, "err");
    }
  }

  return (
    <div>
      <button className="btn-primary" onClick={regen} disabled={running}
        style={{fontSize:".8rem", padding:".4rem .9rem"}}>
        ⟳ Re-generate Image
        {running && <div className="spin" style={{display:"block"}}/>}
      </button>
      {log && (
        <div className={`step-log vis${log.toLowerCase().includes("error") ? " err" : ""}`}
          style={{marginTop:".4rem", fontSize:".74rem"}}>{log}</div>
      )}
    </div>
  );
}

// ── Per-scene video clip re-render button ──────────────────────────────────────

function VideoRegenBtn({ projectName, sceneId, onDone }) {
  const { toast, startPoll, reloadManifest } = useApp();
  const [running,   setRunning]   = useState(false);
  const [annotated, setAnnotated] = useState(false);
  const [progress,  setProgress]  = useState(null);
  const [log,       setLog]       = useState("");

  async function regen() {
    setRunning(true); setLog(""); setProgress(null);
    try {
      const d = await apiPost(`/projects/${projectName}/run/video_scene`, {
        scene_id:            sceneId,
        annotated_subtitles: annotated,
      });
      const stepKey = d.step_key || `video_${sceneId}`;
      startPoll(projectName, stepKey, async (s) => {
        setRunning(false); setProgress(null); setLog(s.log || "");
        if (s.status === "done") {
          toast("Done", "Clip re-rendered.", "ok");
          const m = await reloadManifest(projectName);
          onDone && onDone(m);
        } else if (s.status === "error") {
          toast("Error", s.log, "err");
        }
      }, (s) => setProgress(s.progress || null));
    } catch(e) {
      setRunning(false); setLog(e.message);
      toast("Error", e.message, "err");
    }
  }

  return (
    <div style={{display:"flex", flexDirection:"column", gap:".4rem"}}>
      <div style={{display:"flex", alignItems:"center", gap:".7rem", flexWrap:"wrap"}}>
        <button className="btn-ghost" onClick={regen} disabled={running}
          title="Re-render this scene's clip and the silent pause right after it"
          style={{fontSize:".8rem", padding:".4rem .9rem"}}>
          ⟳ Re-render Clip (+ pause)
          {running && <div className="spin" style={{display:"block", borderTopColor:"var(--muted)"}}/>}
        </button>
        <label style={{display:"flex", alignItems:"center", gap:".3rem",
          fontSize:".76rem", color:"var(--muted)", cursor:"pointer"}}>
          <input type="checkbox" checked={annotated} disabled={running}
            onChange={e=>setAnnotated(e.target.checked)}/>
          annotated subtitles
        </label>
      </div>
      {running && <ProgressBar progress={progress}/>}
      {log && (
        <div className={`step-log vis${log.toLowerCase().includes("error") ? " err" : ""}`}
          style={{marginTop:".2rem", fontSize:".74rem"}}>{log}</div>
      )}
    </div>
  );
}

// ── Scene edit zone (text + prompt) ───────────────────────────────────────────

function SceneEditZone({ scene, projectName, onSaved }) {
  const { toast } = useApp();
  const [text,    setText]    = useState(scene.subtitle_text || "");
  const [saving,  setSaving]  = useState(false);
  const [notice,  setNotice]  = useState(false);

  async function save() {
    setSaving(true);
    try {
      await apiPatch(`/projects/${projectName}/scenes/${scene.id}`, {
        subtitle_text: text.trim(),
        tts_text:      text.trim(),
      });
      toast("Saved", "Scene text updated.", "ok");
      setNotice(true);
      onSaved && onSaved();
    } catch(e) { toast("Error", e.message, "err"); }
    finally { setSaving(false); }
  }

  return (
    <div className="edit-zone" style={{marginTop:"1rem"}}>
      <div className="edit-grid">
        <div className="edit-f">
          <label>Text (German)</label>
          <textarea rows={3} value={text} onChange={e => setText(e.target.value)}/>
        </div>
      </div>
      <div className="edit-actions">
        <button className="edit-save" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
        {notice && (
          <span className="edit-notice">Saved — re-run Audio &amp; Image to apply.</span>
        )}
      </div>
    </div>
  );
}

// ── Generic scene card ─────────────────────────────────────────────────────────

// Map stored reference_type → UI selector value
function _toCharMode(refType) {
  if (refType === "none")          return "none";
  if (refType === "single_speaker") return "single_speaker";
  if (refType === "reading_cast")   return "reading_cast";
  return "both";
}

const CHAR_MODE_OPTIONS = [
  { value: "both",           label: "Both characters" },
  { value: "single_speaker", label: "Speaker only"    },
  { value: "none",           label: "None (text only)" },
];

function SceneCard({ scene, projectName, onChanged, num, castOptions }) {
  const [open,           setOpen]           = useState(false);
  const [editing,        setEditing]        = useState(false);
  const [imgVersion,     setImgVersion]     = useState(Date.now());
  const [useLocationRef, setUseLocationRef] = useState(true);
  const [charactersMode, setCharactersMode] = useState(
    _toCharMode(scene.image?.reference_type)
  );
  // Cast-picker scenes: reading_together scenes AND multi-character dialog scenes
  // both choose which characters appear from a list (vs the none/single/both radio).
  const isReadingCast = scene.image?.reference_type === "reading_cast"
    || scene.image?.reference_type === "multi" || !!scene._reading;
  const [selectedCast, setSelectedCast] = useState(() => new Set(scene.image?._cast || []));
  const toggleCast = (key) => setSelectedCast(prev => {
    const n = new Set(prev);
    n.has(key) ? n.delete(key) : n.add(key);
    return n;
  });

  const isNarration  = !!scene._is_narration;
  const isRepetition = !!scene._is_repetition;
  const isSfx        = scene.audio?.type === "sfx";
  const isDialog     = !isNarration && !isRepetition && !isSfx && scene.audio?.type === "tts";

  const hasImg   = !!scene.image?.file_path;
  const hasAudio = !!scene.audio?.file_path;

  const text    = scene.subtitle_text || scene.audio?.tts_text || scene.description || "—";
  const speaker = scene.characters?.[0] || null;

  // Label chip
  let label, labelStyle;
  if (isNarration) {
    label = "NAR"; labelStyle = {background:"var(--blue)", color:"#fff"};
  } else if (isRepetition) {
    label = "REP"; labelStyle = {background:"var(--purple)", color:"#0d0d10"};
  } else if (isSfx) {
    label = "SFX"; labelStyle = {background:"var(--muted)", color:"#fff", fontSize:".62rem"};
  } else {
    label = speaker || "DLG"; labelStyle = {background:"var(--orange)", color:"#0d0d10"};
  }

  const promptId = `prompt-${scene.id}`;

  return (
    <div className={"item-card" + (open ? " open" : "")}>
      <div className="item-head" onClick={() => setOpen(o => !o)}>
        {num != null && (
          <div className="item-seq" style={{color:"var(--muted)", fontSize:".72rem",
            fontWeight:600, minWidth:"2rem", textAlign:"right",
            fontVariantNumeric:"tabular-nums"}}>#{num}</div>
        )}
        <div className="item-index" style={labelStyle}>{label}</div>
        <div className="item-text" style={{flex:1}}>{text}</div>
        {hasImg && (
          <span className="item-status-badge badge-done" style={{marginLeft:".3rem"}}>img ✓</span>
        )}
        {hasAudio && (
          <span className="item-status-badge badge-done" style={{marginLeft:".3rem"}}>audio ✓</span>
        )}
        {!hasImg && scene.image && (
          <span className="item-status-badge badge-idle" style={{marginLeft:".3rem"}}>no img</span>
        )}
        {!hasAudio && scene.audio?.type === "tts" && (
          <span className="item-status-badge badge-idle" style={{marginLeft:".3rem"}}>no audio</span>
        )}
        {(isDialog || isNarration) && (
          <button className="btn-edit"
            onClick={e => { e.stopPropagation(); setEditing(v => !v); setOpen(true); }}>
            ✎ Edit
          </button>
        )}
        <div className="chevron" style={{marginLeft:".5rem"}}>▼</div>
      </div>

      {open && (
        <div className="item-body">
          {/* Scene visual description (dialog scenes) */}
          {scene.scene_visual && (
            <div style={{fontSize:".8rem", color:"var(--muted)", marginTop:".7rem",
              fontStyle:"italic", borderLeft:"2px solid var(--border)", paddingLeft:".7rem"}}>
              <span style={{fontWeight:600, fontStyle:"normal", color:"var(--fg)"}}>Visual: </span>
              {scene.scene_visual}
            </div>
          )}

          {/* Media row */}
          <div style={{display:"flex", gap:"1.2rem", marginTop:"1rem", flexWrap:"wrap", alignItems:"flex-start"}}>
            {hasImg ? (
              <img className="item-image"
                src={sceneImgSrc(projectName, scene.image.file_path, imgVersion)}
                alt={scene.id}/>
            ) : scene.image ? (
              <div className="item-no-image">No image yet.</div>
            ) : null}

            {hasAudio && (
              <div>
                <div className="mf-label" style={{marginBottom:".35rem"}}>Audio</div>
                <audio controls src={sceneAudioSrc(projectName, scene.audio.file_path)}
                  style={{height:"36px", width:"220px"}}/>
              </div>
            )}
          </div>

          {/* Edit zone */}
          {editing && (isDialog || isNarration) && (
            <SceneEditZone scene={scene} projectName={projectName}
              onSaved={() => { onChanged && onChanged(); setEditing(false); }}/>
          )}

          {/* Image prompt + regen (scenes that have an image) */}
          {scene.image && (
            <>
              <div className="prompt-section" style={{marginTop:"1rem"}}>
                <div className="prompt-header"><span>Image Prompt</span></div>
                <textarea className="prompt-editor" id={promptId}
                  defaultValue={scene.image.prompt_to_create || ""}
                  style={{minHeight:"90px"}}/>
              </div>
            </>
          )}

          {/* Image regen options (only for scenes with an image) */}
          {scene.image && (
            <div style={{marginTop:".8rem", display:"flex", flexDirection:"column", gap:".5rem"}}>
              {/* Characters in image */}
              {isReadingCast ? (
              <div>
                <div style={{fontSize:".78rem", fontWeight:500, marginBottom:".3rem",
                  color:"var(--fg)"}}>Characters in image</div>
                {(castOptions && castOptions.length) ? (
                  <div style={{display:"flex", gap:".4rem", flexWrap:"wrap"}}>
                    {castOptions.map(opt => {
                      const on = selectedCast.has(opt.key);
                      return (
                        <label key={opt.key}
                          style={{display:"flex", alignItems:"center", gap:".3rem",
                            fontSize:".76rem", cursor:"pointer", padding:".25rem .55rem",
                            borderRadius:"5px",
                            border:`1px solid ${on ? "var(--accent)" : "var(--border)"}`,
                            background: on ? "rgba(var(--accent-rgb,99,102,241),.1)" : "var(--surface-2)",
                            color: on ? "var(--accent)" : "var(--muted)"}}>
                          <input type="checkbox" checked={on}
                            onChange={() => toggleCast(opt.key)}
                            style={{display:"none"}}/>
                          {on ? "✓ " : ""}{opt.label}
                        </label>
                      );
                    })}
                  </div>
                ) : (
                  <div style={{fontSize:".76rem", color:"var(--muted)"}}>
                    No cast yet — run the <strong>Cast Characters</strong> step first.
                  </div>
                )}
                <div style={{fontSize:".72rem", color:"var(--muted)", marginTop:".25rem",
                  fontStyle:"italic"}}>
                  Pick which characters to composite into this scene. None selected → scenery only.
                </div>
              </div>
              ) : (
              <div>
                <div style={{fontSize:".78rem", fontWeight:500, marginBottom:".3rem",
                  color:"var(--fg)"}}>Characters in image</div>
                <div style={{display:"flex", gap:".4rem", flexWrap:"wrap"}}>
                  {CHAR_MODE_OPTIONS.map(opt => (
                    <label key={opt.value}
                      style={{
                        display:"flex", alignItems:"center", gap:".3rem",
                        fontSize:".76rem", cursor:"pointer",
                        padding:".25rem .55rem",
                        borderRadius:"5px",
                        border:`1px solid ${charactersMode === opt.value ? "var(--accent)" : "var(--border)"}`,
                        background: charactersMode === opt.value ? "rgba(var(--accent-rgb,99,102,241),.1)" : "var(--surface-2)",
                        color: charactersMode === opt.value ? "var(--accent)" : "var(--muted)",
                        transition:"border .15s, color .15s",
                      }}>
                      <input type="radio" name={`char-mode-${scene.id}`}
                        value={opt.value}
                        checked={charactersMode === opt.value}
                        onChange={() => setCharactersMode(opt.value)}
                        style={{display:"none"}}/>
                      {opt.label}
                    </label>
                  ))}
                </div>
                {charactersMode === "none" && (
                  <div style={{fontSize:".73rem", color:"var(--muted)", marginTop:".25rem",
                    fontStyle:"italic"}}>
                    Image generated from text only — no character reference art used.
                  </div>
                )}
              </div>
              )}

              {/* Location ref toggle */}
              {charactersMode !== "none" && !isReadingCast && (
                <div style={{display:"flex", flexDirection:"column", gap:".2rem"}}>
                  <div className="toggle-row" style={{fontSize:".78rem"}}>
                    <input type="checkbox" id={`loc-ref-${scene.id}`}
                      checked={useLocationRef}
                      onChange={e => setUseLocationRef(e.target.checked)}/>
                    <label htmlFor={`loc-ref-${scene.id}`}>Include location in reference image</label>
                  </div>
                  {!useLocationRef && (
                    <div style={{fontSize:".74rem", color:"var(--muted)", paddingLeft:"1.5rem",
                      fontStyle:"italic"}}>
                      Only character art will be sent — the model will invent the background.
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Action buttons row */}
          {(scene.image || scene.audio?.type === "tts") && (
            <div className="run-row" style={{flexWrap:"wrap", gap:".5rem", alignItems:"flex-start"}}>
              {scene.image && (
                <ImageRegenBtn projectName={projectName} sceneId={scene.id}
                  promptId={promptId} useLocationRef={useLocationRef}
                  charactersMode={charactersMode}
                  cast={isReadingCast ? Array.from(selectedCast) : null}
                  onDone={m => { setImgVersion(Date.now()); onChanged && onChanged(m); }}/>
              )}
              {scene.audio?.type === "tts" && (
                <AudioRegenBtn projectName={projectName} sceneId={scene.id}
                  onDone={m => { onChanged && onChanged(m); }}/>
              )}
              <VideoRegenBtn projectName={projectName} sceneId={scene.id}
                onDone={m => { onChanged && onChanged(m); }}/>
            </div>
          )}

          {/* Grammar annotation viewer / editor (dialogue & reading sentences) */}
          {scene.audio?.type === "tts" && !isNarration && !isRepetition && (
            <AnnotationPanel projectName={projectName} sceneId={scene.id}/>
          )}
        </div>
      )}
    </div>
  );
}

// ── Pause scene card ───────────────────────────────────────────────────────────

function PauseCard({ scene, projectName, onChanged, num }) {
  const { toast } = useApp();
  const [durMs,   setDurMs]   = useState(String(scene.duration_ms ?? 350));
  const [saving,  setSaving]  = useState(false);
  const [saved,   setSaved]   = useState(false);

  const durNum  = parseInt(durMs, 10);
  const isValid = !isNaN(durNum) && durNum >= 0 && durNum <= 10000;
  const dirty   = durNum !== (scene.duration_ms ?? 350);

  async function save() {
    if (!isValid) return;
    setSaving(true); setSaved(false);
    try {
      await apiPatch(`/projects/${projectName}/scenes/${scene.id}`, {
        duration_ms: durNum,
      });
      toast("Saved", `Pause ${scene.id} set to ${durNum} ms.`, "ok");
      setSaved(true);
      onChanged && onChanged();
    } catch(e) { toast("Error", e.message, "err"); }
    finally { setSaving(false); }
  }

  return (
    <div className="item-card">
      <div className="item-head" style={{cursor:"default"}}>
        {num != null && (
          <div className="item-seq" style={{color:"var(--muted)", fontSize:".72rem",
            fontWeight:600, minWidth:"2rem", textAlign:"right",
            fontVariantNumeric:"tabular-nums"}}>#{num}</div>
        )}
        <div className="item-index"
          style={{background:"var(--border)", color:"var(--muted)", fontSize:".62rem",
                  letterSpacing:".04em"}}>
          PSE
        </div>
        <div style={{flex:1, display:"flex", alignItems:"center", gap:".75rem"}}>
          <span style={{color:"var(--muted)", fontSize:".82rem"}}>Silent pause</span>
          <div style={{display:"flex", alignItems:"center", gap:".4rem"}}>
            <input
              type="number"
              min="0"
              max="10000"
              step="50"
              value={durMs}
              onChange={e => { setDurMs(e.target.value); setSaved(false); }}
              style={{
                width:"90px", padding:".25rem .5rem", fontSize:".84rem",
                borderRadius:"5px", border:"1px solid var(--border)",
                background:"var(--surface-2)", color:"var(--fg)",
                borderColor: isValid ? "var(--border)" : "var(--red, #f87171)",
              }}
            />
            <span style={{color:"var(--muted)", fontSize:".78rem"}}>ms</span>
          </div>
          {saved && (
            <span style={{fontSize:".74rem", color:"var(--green, #4ade80)"}}>✓ saved</span>
          )}
        </div>
        {dirty && isValid && (
          <button className="btn-edit" onClick={save} disabled={saving}
            style={{marginLeft:".5rem"}}>
            {saving ? "…" : "Save"}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Reading cast gallery ───────────────────────────────────────────────────────

function ReadingCastGallery({ castChars, castAssets, allChars }) {
  if (!castChars || !castChars.length) return null;
  return (
    <div className="item-card" style={{padding:".9rem 1rem", marginBottom:".7rem"}}>
      <div style={{fontWeight:600, marginBottom:".6rem"}}>
        Story cast <span style={{color:"var(--muted)", fontWeight:400}}>({castChars.length})</span>
      </div>
      <div style={{display:"flex", gap:".8rem", flexWrap:"wrap"}}>
        {castChars.map(c => {
          const key = castAssets ? castAssets[c.name] : null;
          const ch  = (key && allChars) ? allChars[key] : null;
          // Auto-generated rt_ characters expose ref_image_file_path; an existing
          // character cast in this role uses its own thumbnail / 3-4 art instead.
          const ref = ch && (ch.ref_image_file_path || ch.thumbnail_file_path || ch.art_34left_file_path);
          const mapped = !!(key && !String(key).startsWith("rt_"));
          return (
            <div key={c.name} style={{width:"118px", display:"flex", flexDirection:"column", alignItems:"center"}}>
              <div style={{width:"118px", height:"118px", borderRadius:"8px", overflow:"hidden",
                background:"var(--surface-2)", border:"1px solid var(--border)",
                display:"flex", alignItems:"center", justifyContent:"center"}}>
                {ref ? (
                  <img src={`/asset-files/${ref}?t=${Date.now()}`} alt={c.name}
                    style={{width:"100%", height:"100%", objectFit:"cover"}}/>
                ) : (
                  <span style={{fontSize:".7rem", color:"var(--muted)", textAlign:"center", padding:"0 .3rem"}}>
                    not generated
                  </span>
                )}
              </div>
              <div style={{fontSize:".82rem", fontWeight:600, marginTop:".35rem", textAlign:"center"}}>{c.name}</div>
              <div style={{fontSize:".7rem", color:"var(--muted)"}}>{c.kind}</div>
              {mapped && (
                <div style={{fontSize:".66rem", color:"var(--accent)", fontWeight:600, marginTop:".1rem",
                  textAlign:"center"}}>
                  ★ played by {(ch && ch.name) || key}
                </div>
              )}
              <div title={c.description}
                style={{fontSize:".7rem", color:"var(--muted)", textAlign:"center", marginTop:".15rem",
                  display:"-webkit-box", WebkitLineClamp:3, WebkitBoxOrient:"vertical", overflow:"hidden"}}>
                {c.description}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Bulk after-pause control ────────────────────────────────────────────────────

function BulkPauseControl({ projectName, onChanged }) {
  const { toast } = useApp();
  const [ms,     setMs]     = useState("350");
  const [scope,  setScope]  = useState("all");
  const [saving, setSaving] = useState(false);

  const num     = parseInt(ms, 10);
  const isValid = !isNaN(num) && num >= 0 && num <= 10000;

  async function apply() {
    if (!isValid) return;
    setSaving(true);
    try {
      const d = await apiPatch(`/projects/${projectName}/pauses`, {
        duration_ms: num, scope,
      });
      toast("Saved",
        `Updated ${d.updated} pause${d.updated !== 1 ? "s" : ""} to ${num} ms — re-render clips to apply.`,
        "ok");
      onChanged && onChanged();
    } catch(e) { toast("Error", e.message, "err"); }
    finally { setSaving(false); }
  }

  return (
    <div className="item-card" style={{padding:".9rem 1rem", marginBottom:".7rem"}}>
      <div style={{fontWeight:600, marginBottom:".55rem"}}>
        After-pause (bulk)
        <span style={{color:"var(--muted)", fontWeight:400, fontSize:".78rem", marginLeft:".4rem"}}>
          set the silent gap after scenes in one shot
        </span>
      </div>
      <div style={{display:"flex", alignItems:"flex-end", gap:".7rem", flexWrap:"wrap"}}>
        <div className="field" style={{maxWidth:"8rem"}}>
          <label>Duration (ms)</label>
          <input type="number" min="0" max="10000" step="50"
            value={ms} onChange={e=>setMs(e.target.value)}
            style={{borderColor: isValid ? "" : "var(--red, #f87171)"}}/>
        </div>
        <div className="field" style={{maxWidth:"15rem"}}>
          <label>Apply to</label>
          <select value={scope} onChange={e=>setScope(e.target.value)}>
            <option value="all">All pauses</option>
            <option value="dialog">Pauses after dialog lines only</option>
          </select>
        </div>
        <button className="btn-primary" onClick={apply} disabled={saving || !isValid}
          style={{fontSize:".82rem"}}>
          {saving ? "Applying…" : "Apply"}
        </button>
      </div>
      <div style={{fontSize:".74rem", color:"var(--muted)", marginTop:".5rem", fontStyle:"italic"}}>
        Updates the silent pause scenes in the manifest. Re-render the affected clips
        (or the whole Video step) to bake the new gap into the video.
      </div>
    </div>
  );
}

// ── Shadowing repeat-scenes control ──────────────────────────────────────────────

function RepeatScenesControl({ projectName, count, onChanged }) {
  const { toast } = useApp();
  const [busy,   setBusy]   = useState(false);
  const [factor, setFactor] = useState("1.0");

  async function run(action) {
    setBusy(true);
    try {
      const body = { action };
      if (action === "add" && factor.trim()) body.factor = parseFloat(factor);
      const d = await apiPost(`/projects/${projectName}/repeat_scenes`, body);
      if (action === "add") {
        toast("Done", `Added ${d.added} repeat scene${d.added !== 1 ? "s" : ""} (${d.total_repeat} total). Render the Video step to apply.`, "ok");
      } else {
        toast("Done", `Removed ${d.removed} repeat scene${d.removed !== 1 ? "s" : ""}.`, "ok");
      }
      onChanged && onChanged();
    } catch(e) { toast("Error", e.message, "err"); }
    finally { setBusy(false); }
  }

  const fNum   = parseFloat(factor);
  const fValid = factor.trim() === "" || (!isNaN(fNum) && fNum >= 0.1 && fNum <= 10);

  return (
    <div className="item-card" style={{padding:".9rem 1rem", marginBottom:".7rem"}}>
      <div style={{fontWeight:600, marginBottom:".15rem"}}>
        Shadowing “repeat” scenes
        {count > 0 && (
          <span style={{color:"var(--accent)", fontWeight:600, fontSize:".78rem", marginLeft:".5rem"}}>
            {count} active
          </span>
        )}
      </div>
      <div style={{fontSize:".76rem", color:"var(--muted)", marginBottom:".55rem"}}>
        Inserts an intermediate scene after each dialog line — the same image with the subtitle still
        readable, plus a centered “now repeat” message — so learners can shadow the line. Customize the
        message &amp; font size in the <strong>Video</strong> step (defaults in <code>config.ini</code>).
      </div>
      <div style={{display:"flex", gap:".7rem", alignItems:"flex-end", flexWrap:"wrap"}}>
        <div className="field" style={{maxWidth:"9rem"}}>
          <label>Time factor ×</label>
          <input type="number" min="0.1" max="10" step="0.1" value={factor}
            onChange={e=>setFactor(e.target.value)}
            style={{borderColor: fValid ? "" : "var(--red, #f87171)"}}/>
        </div>
        <button className="btn-primary" onClick={() => run("add")} disabled={busy || !fValid}
          style={{fontSize:".82rem"}}>
          {busy ? "Working…" : (count > 0 ? "Re-sync repeat scenes" : "Add repeat scenes")}
        </button>
        {count > 0 && (
          <button className="btn-cancel" onClick={() => run("remove")} disabled={busy}
            style={{fontSize:".82rem"}}>
            Remove all
          </button>
        )}
      </div>
      <div style={{fontSize:".73rem", color:"var(--muted)", marginTop:".4rem", fontStyle:"italic"}}>
        Each repeat scene is held for the dialog line's spoken length × this factor (e.g. 1.5 = 50% more
        time to read/repeat). Re-syncing recomputes every hold; individual holds stay editable per card.
      </div>
    </div>
  );
}

// ── Repeat scene card ────────────────────────────────────────────────────────────

function RepeatCard({ scene, projectName, onChanged, num }) {
  const { toast } = useApp();
  const [durMs,  setDurMs]  = useState(String(scene.duration_ms ?? 2500));
  const [saving, setSaving] = useState(false);
  const [saved,  setSaved]  = useState(false);

  const durNum  = parseInt(durMs, 10);
  const isValid = !isNaN(durNum) && durNum >= 0 && durNum <= 10000;
  const dirty   = durNum !== (scene.duration_ms ?? 2500);

  async function save() {
    if (!isValid) return;
    setSaving(true); setSaved(false);
    try {
      await apiPatch(`/projects/${projectName}/scenes/${scene.id}`, { duration_ms: durNum });
      toast("Saved", `Repeat hold set to ${durNum} ms.`, "ok");
      setSaved(true);
      onChanged && onChanged();
    } catch(e) { toast("Error", e.message, "err"); }
    finally { setSaving(false); }
  }

  return (
    <div className="item-card">
      <div className="item-head" style={{cursor:"default"}}>
        {num != null && (
          <div className="item-seq" style={{color:"var(--muted)", fontSize:".72rem",
            fontWeight:600, minWidth:"2rem", textAlign:"right",
            fontVariantNumeric:"tabular-nums"}}>#{num}</div>
        )}
        <div className="item-index"
          style={{background:"var(--purple)", color:"#0d0d10", fontSize:".62rem",
                  letterSpacing:".04em"}}>
          RPT
        </div>
        <div style={{flex:1, display:"flex", alignItems:"center", gap:".75rem", flexWrap:"wrap"}}>
          <span style={{color:"var(--muted)", fontSize:".82rem"}}>
            Repeat prompt
            {scene.subtitle_text && (
              <span style={{color:"var(--fg)", fontStyle:"italic", marginLeft:".4rem"}}>
                “{scene.subtitle_text}”
              </span>
            )}
          </span>
          <div style={{display:"flex", alignItems:"center", gap:".4rem"}}>
            <input type="number" min="0" max="10000" step="50" value={durMs}
              onChange={e => { setDurMs(e.target.value); setSaved(false); }}
              style={{width:"90px", padding:".25rem .5rem", fontSize:".84rem",
                borderRadius:"5px", border:"1px solid var(--border)",
                background:"var(--surface-2)", color:"var(--fg)",
                borderColor: isValid ? "var(--border)" : "var(--red, #f87171)"}}/>
            <span style={{color:"var(--muted)", fontSize:".78rem"}}>ms hold</span>
          </div>
          {saved && <span style={{fontSize:".74rem", color:"var(--green, #4ade80)"}}>✓ saved</span>}
        </div>
        {dirty && isValid && (
          <button className="btn-edit" onClick={save} disabled={saving} style={{marginLeft:".5rem"}}>
            {saving ? "…" : "Save"}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Main tab ───────────────────────────────────────────────────────────────────

function ItemsTab({ projectName }) {
  const { manifest, reloadManifest } = useApp();
  const [allChars, setAllChars] = useState({});

  useEffect(() => {
    fetch("/assets/characters").then(r => r.json()).then(d => setAllChars(d || {})).catch(() => {});
  }, [projectName]);

  // Number every scene by its position in the manifest order (matches scene_NNN / video order)
  const numById = {};
  (manifest?.scenes || []).forEach((s, i) => { numById[s.id] = i + 1; });

  // reading_together cast: descriptions + asset-key map (for the gallery + per-scene picker)
  const reading     = manifest?.generation_config?.reading || {};
  const castChars   = reading.characters || [];
  const castAssets  = reading.cast_assets || {};
  // Per-scene character picker options: reading projects use the rt_ cast-asset map;
  // multi-character conversational projects fall back to the project's character list.
  const projectCast = manifest?.generation_config?.characters || [];
  const castOptions = Object.keys(castAssets).length
    ? Object.entries(castAssets).map(([name, key]) => ({ key, label: name }))
    : projectCast.map(c => ({ key: c, label: c }));

  const scenes = (manifest?.scenes || []).filter(s =>
    // Show TTS, SFX, narration scenes, pure pause scenes AND shadowing repeat scenes
    s.audio !== null || s.image !== null || s.description === "pause" || s._is_repeat_prompt
  );

  async function handleChanged(newManifest) {
    if (!newManifest) await reloadManifest(projectName);
  }

  if (!scenes.length) {
    return (
      <div style={{color:"var(--muted)", fontSize:".88rem", marginTop:"1.2rem",
        padding:"1.2rem", background:"var(--surface-2)", borderRadius:"8px"}}>
        No scenes yet — run the <strong>Script</strong> step first.
      </div>
    );
  }

  const allScenes   = manifest?.scenes || [];
  const hasPauses   = allScenes.some(s => s.description === "pause");
  const repeatCount = allScenes.filter(s => s._is_repeat_prompt).length;
  // The repeat-scenes control is only meaningful for projects with spoken dialog.
  const hasDialog   = allScenes.some(s =>
    (s.audio && s.audio.type === "tts") && !s._is_narration && !s._is_repetition && !s._reading);

  return (
    <div className="items-grid">
      <ReadingCastGallery castChars={castChars} castAssets={castAssets} allChars={allChars}/>
      {hasDialog && (
        <RepeatScenesControl projectName={projectName} count={repeatCount}
          onChanged={() => reloadManifest(projectName)}/>
      )}
      {hasPauses && (
        <BulkPauseControl projectName={projectName}
          onChanged={() => reloadManifest(projectName)}/>
      )}
      {scenes.map(scene =>
        scene._is_repeat_prompt ? (
          <RepeatCard
            key={scene.id}
            scene={scene}
            num={numById[scene.id]}
            projectName={projectName}
            onChanged={handleChanged}
          />
        ) : scene.description === "pause" ? (
          <PauseCard
            key={scene.id}
            scene={scene}
            num={numById[scene.id]}
            projectName={projectName}
            onChanged={handleChanged}
          />
        ) : (
          <SceneCard
            key={scene.id}
            scene={scene}
            num={numById[scene.id]}
            castOptions={castOptions}
            projectName={projectName}
            onChanged={handleChanged}
          />
        )
      )}
    </div>
  );
}
