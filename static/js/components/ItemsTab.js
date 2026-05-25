// ItemsTab.js  — displays scenes[] from the new manifest schema
const { useState } = React;

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

// ── Per-scene image regen button ───────────────────────────────────────────────

function ImageRegenBtn({ projectName, sceneId, promptId, useLocationRef, charactersMode, onDone }) {
  const { toast, startPoll, reloadManifest } = useApp();
  const [running, setRunning] = useState(false);
  const [log,     setLog]     = useState("");

  async function regen() {
    const promptEl      = document.getElementById(promptId);
    const promptOverride = promptEl?.value.trim() || null;
    setRunning(true); setLog("");
    try {
      const d = await apiPost(`/projects/${projectName}/run/image_scene`, {
        scene_id:            sceneId,
        prompt_override:     promptOverride,
        use_location_ref:    useLocationRef,
        characters_override: charactersMode,
      });
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
  return "both";
}

const CHAR_MODE_OPTIONS = [
  { value: "both",           label: "Both characters" },
  { value: "single_speaker", label: "Speaker only"    },
  { value: "none",           label: "None (text only)" },
];

function SceneCard({ scene, projectName, onChanged }) {
  const [open,           setOpen]           = useState(false);
  const [editing,        setEditing]        = useState(false);
  const [imgVersion,     setImgVersion]     = useState(Date.now());
  const [useLocationRef, setUseLocationRef] = useState(true);
  const [charactersMode, setCharactersMode] = useState(
    _toCharMode(scene.image?.reference_type)
  );

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

              {/* Location ref toggle */}
              {charactersMode !== "none" && (
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
            <div className="run-row" style={{flexWrap:"wrap", gap:".5rem"}}>
              {scene.image && (
                <ImageRegenBtn projectName={projectName} sceneId={scene.id}
                  promptId={promptId} useLocationRef={useLocationRef}
                  charactersMode={charactersMode}
                  onDone={m => { setImgVersion(Date.now()); onChanged && onChanged(m); }}/>
              )}
              {scene.audio?.type === "tts" && (
                <AudioRegenBtn projectName={projectName} sceneId={scene.id}
                  onDone={m => { onChanged && onChanged(m); }}/>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Pause scene card ───────────────────────────────────────────────────────────

function PauseCard({ scene, projectName, onChanged }) {
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

// ── Main tab ───────────────────────────────────────────────────────────────────

function ItemsTab({ projectName }) {
  const { manifest, reloadManifest } = useApp();

  const scenes = (manifest?.scenes || []).filter(s =>
    // Show TTS, SFX, narration scenes AND pure pause scenes
    s.audio !== null || s.image !== null || s.description === "pause"
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

  return (
    <div className="items-grid">
      {scenes.map(scene =>
        scene.description === "pause" ? (
          <PauseCard
            key={scene.id}
            scene={scene}
            projectName={projectName}
            onChanged={handleChanged}
          />
        ) : (
          <SceneCard
            key={scene.id}
            scene={scene}
            projectName={projectName}
            onChanged={handleChanged}
          />
        )
      )}
    </div>
  );
}
