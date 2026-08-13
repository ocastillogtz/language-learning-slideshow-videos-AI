// PipelineTab.js
const { useState, useEffect } = React;

const SHOT_TYPES    = ["both", "over_shoulder_A", "over_shoulder_B"];
const PROJECT_TYPES = {
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
};

// Helper: does this project type key use a word list?
const isWordLearningType = t => t === "word_learning" || t === "word_learning_long";
// Helper: does this project type key use pairs (not line count)?
const isPairsType = t => ["register_phrases","grammar_pairs","register_phrases_long","grammar_pairs_long"].includes(t);
// Helper: does this project type support more than two characters in the conversation?
const isMultiCharType = t => ["story","story_long","register_phrases","register_phrases_long",
                              "word_learning","word_learning_long"].includes(t);

// Shared progress bar — fed by the {current,total,label} progress object that
// jobs report while running. Defined here (loaded before ItemsTab) so it is a
// global usable from every component file.
function ProgressBar({ progress }) {
  if (!progress || !progress.total) return null;
  const pct = Math.max(0, Math.min(100,
    Math.round((progress.current / progress.total) * 100)));
  return (
    <div className="progress">
      <div className="progress-track">
        <div className="progress-fill" style={{ width: pct + "%" }}/>
      </div>
      <div className="progress-label">
        {progress.label || `${progress.current}/${progress.total}`} · {pct}%
      </div>
    </div>
  );
}

function StepCard({ step, projectName }) {
  const { toast, startPoll, reloadManifest, refreshSidebar } = useApp();
  const [open,     setOpen]     = useState(false);
  const [status,   setStatus]   = useState("idle");
  const [log,      setLog]      = useState("");
  const [running,  setRunning]  = useState(false);
  const [progress, setProgress] = useState(null);

  const disabledReason = step.disabledReason || null;

  // Fetch current status once on mount
  useEffect(() => {
    if (!projectName) return;
    fetch(`/projects/${projectName}/status/${step.id}`)
      .then(r => r.json())
      .then(s => { setStatus(s.status); setLog(s.log || ""); })
      .catch(() => {});
  }, [projectName, step.id]);

  async function run() {
    setRunning(true);
    setStatus("running");
    setLog("");
    setProgress(null);
    try {
      const payload = step.payload();
      const d = await apiPost(step.endpoint(projectName), payload);
      const stepKey = d.step_key || step.id;
      startPoll(projectName, stepKey, async (s) => {
        setStatus(s.status);
        setLog(s.log || "");
        setRunning(false);
        setProgress(null);
        if (s.status === "done") {
          toast("Done", `${step.title} completed.`, "ok");
          await reloadManifest(projectName);
          await refreshSidebar();
        } else if (s.status === "error") {
          toast("Error", s.log, "err");
        }
      }, (s) => setProgress(s.progress || null));
    } catch(e) {
      setStatus("error"); setLog(e.message); setRunning(false); setProgress(null);
      toast("Error", e.message, "err");
    }
  }

  const badgeClass = { idle:"badge-idle", running:"badge-running", done:"badge-done", error:"badge-error" }[status] || "badge-idle";

  return (
    <div className={"step-card" + (open ? " open" : "")}>
      <div className="step-head" onClick={() => setOpen(o => !o)}>
        <div className="step-num">{step.num}</div>
        <div style={{flex:1}}>
          <div className="step-title">{step.title}</div>
          <div className="step-desc">{step.desc}</div>
        </div>
        <div className={`badge ${badgeClass}`}>{status}</div>
        <div className="chevron">▼</div>
      </div>
      {open && (
        <div className="step-body">
          <step.Fields projectName={projectName} />
          {disabledReason && (
            <div className="step-log vis err" style={{marginBottom:".5rem"}}>
              ⚠ {disabledReason}
            </div>
          )}
          <div className="run-row">
            <button className="btn-primary" onClick={run} disabled={running || !!disabledReason}
              title={disabledReason || undefined}>
              <svg width="11" height="11" viewBox="0 0 11 11" fill="currentColor">
                <polygon points="1,0.5 10.5,5.5 1,10.5"/>
              </svg>
              Run
              {running && <div className="spin" style={{display:"block"}}/>}
            </button>
          </div>
          {running && <ProgressBar progress={progress}/>}
          {log && (
            <div className={`step-log vis${status==="error"?" err":""}`}>{log}</div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Step field components ──────────────────────────────────────────────────────

function ScriptFields({ projectName }) {
  const { manifest, characters, locations, toast } = useApp();
  const m   = manifest || {};
  const gen = m.generation_config || {};
  const meta= m.project_metadata  || {};

  const [projType,     setProjType]     = useState(meta.project_type_key || gen.project_type_key || "story");
  const [charA,        setCharA]        = useState((gen.characters||[])[0] || "");
  const [charB,        setCharB]        = useState((gen.characters||[])[1] || "");
  // Extra cast beyond A and B (multi-character conversational types).
  const [extraChars,   setExtraChars]   = useState(() => (gen.characters || []).slice(2));
  const [useLocation,  setUseLocation]  = useState(!!(gen.location_key));
  const [loc,          setLoc]          = useState(gen.location_key || "");
  const [dialogCount,  setDialogCount]  = useState(String(gen.dialog_count || ""));
  const [prompt,       setPrompt]       = useState(gen.prompt_script || "");
  // Baseline = the last auto-generated prompt we put in the box (initial manifest
  // value or a Preview load). We only send prompt_override when the user has actually
  // EDITED the prompt away from this baseline — otherwise echoing the auto-prompt back
  // would be treated as a custom override and silently disable batched generation.
  const [promptBaseline, setPromptBaseline] = useState(gen.prompt_script || "");
  const [words,        setWords]        = useState((gen.words || []).join(", "));
  const [loading,      setLoading]      = useState(false);

  // Auto-detect characters from scene description if not already set
  useEffect(() => {
    if ((charA && charB) || !characters.length) return;
    const context = (gen.provided_context || "").toLowerCase();
    if (!context) return;
    const found = characters.filter(c => context.includes(c.toLowerCase()));
    if (found.length >= 1 && !charA) setCharA(found[0]);
    if (found.length >= 2 && !charB) setCharB(found[1]);
  }, [characters]);

  // Full cast (A + B + extras), de-duplicated, blanks removed.
  const fullCast = () => {
    const out = [];
    [charA, charB, ...extraChars].forEach(c => { if (c && !out.includes(c)) out.push(c); });
    return out;
  };

  ScriptFields._getPayload = () => ({
    char_a:           charA,
    char_b:           charB,
    characters:       isMultiCharType(projType) ? fullCast() : undefined,
    location_key:     useLocation ? loc : null,
    project_type_key: projType,
    // Only a genuinely edited prompt counts as an override; an untouched auto-prompt
    // is sent as null so the backend can auto-build it and batch long dialogs.
    prompt_override:  (prompt.trim() && prompt.trim() !== (promptBaseline || "").trim())
                        ? prompt.trim() : null,
    dialog_count:     dialogCount !== "" ? parseInt(dialogCount, 10) : null,
    words:            isWordLearningType(projType)
                        ? words.split(",").map(w => w.trim()).filter(Boolean)
                        : undefined,
  });

  async function loadPrompt() {
    if (!charA || !charB || (useLocation && !loc)) {
      toast("Warning", "Select characters" + (useLocation ? " and location" : "") + " first.", "err"); return;
    }
    setLoading(true);
    try {
      const d = await apiPost(`/projects/${projectName}/prompt/script`, {
        char_a: charA, char_b: charB,
        characters: isMultiCharType(projType) ? fullCast() : undefined,
        location_key: useLocation ? loc : null,
        project_type_key: projType,
        dialog_count: dialogCount !== "" ? parseInt(dialogCount, 10) : null,
        words: isWordLearningType(projType)
          ? words.split(",").map(w => w.trim()).filter(Boolean)
          : undefined,
      });
      setPrompt(d.prompt);
      setPromptBaseline(d.prompt);   // a previewed prompt is still "auto", not a user edit
    } catch(e) { toast("Error", e.message, "err"); }
    finally { setLoading(false); }
  }

  // Determine label for dialog count based on project type
  const dialogLabel       = isPairsType(projType) ? "Number of pairs"        : "Number of dialog lines";
  const dialogPlaceholder = isPairsType(projType) ? "e.g. 4 (default: 4–6)"  : "e.g. 5 (default: 4–6)";

  return (
    <div className="fields">
      <div className="field-row">
        <div className="field">
          <label>Character A</label>
          <select value={charA} onChange={e=>setCharA(e.target.value)}>
            <option value="">— select —</option>
            {characters.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="field">
          <label>Character B</label>
          <select value={charB} onChange={e=>setCharB(e.target.value)}>
            <option value="">— select —</option>
            {characters.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      </div>

      {/* Additional characters — only for multi-character conversational types */}
      {isMultiCharType(projType) && (
        <div>
          <label style={{fontWeight:500, fontSize:".82rem"}}>
            Additional characters{" "}
            <span style={{color:"var(--muted)",fontWeight:300}}>(optional — for a 3+ person conversation)</span>
          </label>
          <div style={{display:"flex", gap:".4rem", flexWrap:"wrap", marginTop:".35rem"}}>
            {characters.filter(c => c !== charA && c !== charB && c !== "Narrator").map(c => {
              const on = extraChars.includes(c);
              return (
                <label key={c}
                  style={{display:"flex", alignItems:"center", gap:".3rem", fontSize:".76rem",
                    cursor:"pointer", padding:".25rem .55rem", borderRadius:"5px",
                    border:`1px solid ${on ? "var(--accent)" : "var(--border)"}`,
                    background: on ? "rgba(var(--accent-rgb,99,102,241),.1)" : "var(--surface-2)",
                    color: on ? "var(--accent)" : "var(--muted)"}}>
                  <input type="checkbox" checked={on} style={{display:"none"}}
                    onChange={() => setExtraChars(prev =>
                      prev.includes(c) ? prev.filter(x => x !== c) : [...prev, c])}/>
                  {on ? "✓ " : ""}{c}
                </label>
              );
            })}
          </div>
          <div style={{fontSize:".73rem", color:"var(--muted)", marginTop:".3rem", fontStyle:"italic"}}>
            Any selected character can speak and appear on screen. Leave empty for a normal two-person dialog.
          </div>
        </div>
      )}

      {/* Location — optional via checkbox */}
      <div>
        <div className="toggle-row" style={{marginBottom:".4rem"}}>
          <input type="checkbox" id="f_use_loc" checked={useLocation}
            onChange={e => setUseLocation(e.target.checked)}/>
          <label htmlFor="f_use_loc" style={{fontWeight:500}}>Use specific location</label>
        </div>
        {useLocation ? (
          <div className="field" style={{marginTop:".1rem"}}>
            <select value={loc} onChange={e=>setLoc(e.target.value)}>
              <option value="">— select location —</option>
              {locations.map(l => <option key={l} value={l}>{l}</option>)}
            </select>
          </div>
        ) : (
          <div style={{fontSize:".76rem", color:"var(--muted)", paddingLeft:"1.6rem",
            fontStyle:"italic", marginBottom:".6rem"}}>
            The model will choose a suitable setting based on the scene content.
          </div>
        )}
      </div>

      <div className="field-row">
        <div className="field" style={{flex:2}}>
          <label>Project Type</label>
          <select value={projType} onChange={e=>setProjType(e.target.value)}>
            <optgroup label="▸ Vertical — 1080×1920 (Shorts / Reels)">
              {PROJECT_TYPES.vertical.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </optgroup>
            <optgroup label="▸ Horizontal — 1920×1080 Full HD (YouTube)">
              {PROJECT_TYPES.horizontal.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </optgroup>
          </select>
        </div>
        <div className="field" style={{flex:1}}>
          <label>{dialogLabel}
            <span style={{color:"var(--muted)",fontWeight:300,marginLeft:".3rem"}}>(optional)</span>
          </label>
          <input
            type="number" min="1" max="20" step="1"
            value={dialogCount}
            onChange={e => setDialogCount(e.target.value)}
            placeholder={dialogPlaceholder}
          />
        </div>
      </div>

      {isWordLearningType(projType) && (
        <div className="field">
          <label>
            Words to teach{" "}
            <span style={{color:"var(--muted)",fontWeight:300}}>(comma-separated)</span>
          </label>
          <textarea
            className="prompt-editor"
            rows={3}
            value={words}
            onChange={e => setWords(e.target.value)}
            placeholder="e.g. laufen, rennen, der Bahnhof, ankommen"
            style={{fontFamily:"inherit"}}
          />
        </div>
      )}
      <div className="prompt-section">
        <div className="prompt-header">
          <span>GPT Prompt Override (optional)</span>
          <button className="btn-ghost" onClick={loadPrompt}
            style={{fontSize:".74rem",padding:".3rem .7rem"}} disabled={loading}>
            {loading ? "Loading…" : "⟳ Preview Prompt"}
          </button>
        </div>
        <textarea className="prompt-editor" value={prompt}
          onChange={e=>setPrompt(e.target.value)}
          placeholder="Leave blank for auto-generated prompt. Click 'Preview' to inspect it first."/>
      </div>
    </div>
  );
}

function AudioFields() {
  const [overwrite, setOverwrite] = useState(false);

  AudioFields._getPayload = () => ({ overwrite });

  return (
    <div className="fields">
      <div style={{color:"var(--muted)",fontSize:".84rem",marginBottom:".2rem"}}>
        Voices are defined in <code>characters.json</code>.
      </div>

      <div className="toggle-row">
        <input type="checkbox" id="f_ow_audio" checked={overwrite}
          onChange={e=>setOverwrite(e.target.checked)}/>
        <label htmlFor="f_ow_audio">Redo all (re-synthesize audio that already exists)</label>
      </div>
      <div style={{fontSize:".76rem", color:"var(--muted)", paddingLeft:"1.6rem",
        fontStyle:"italic", marginTop:"-.2rem"}}>
        {overwrite
          ? "Every TTS line is regenerated, overwriting existing files."
          : "Only lines without audio yet are generated; existing files are reused."}
      </div>

      <div style={{fontSize:".76rem", color:"var(--muted)", marginTop:".5rem"}}>
        Interrupted run? Use <strong>⟳ Check for updates</strong> at the top of the project to
        import audio/images already on disk into the manifest.
      </div>
    </div>
  );
}

function ImagesFields() {
  const { manifest } = useApp();
  const isHorizontal = (manifest?.video_info?.video_format) === "horizontal";
  const [overwrite,       setOverwrite]       = useState(false);
  const [ignoreCache,     setIgnoreCache]     = useState(false);
  const [useLocationRef,  setUseLocationRef]  = useState(true);
  const [mosaicMode,      setMosaicMode]      = useState(false);
  const [imageModels,     setImageModels]     = useState([]);
  const [imageModel,      setImageModel]      = useState("");
  useEffect(() => {
    fetchImageModels().then(d => {
      setImageModels(d.models || []);
      setImageModel(d.default_key || "");
    });
  }, []);
  // Mosaic mode is horizontal-only; never send it for vertical projects.
  ImagesFields._getPayload = () => ({
    overwrite,
    ignore_cache:      ignoreCache,
    use_location_ref:  useLocationRef,
    mosaic_mode:       isHorizontal && mosaicMode,
    // Blank = use the config default model.
    model:             imageModel || undefined,
  });
  return (
    <div className="fields">
      {imageModels.length > 0 && (
        <div className="field" style={{maxWidth:"19rem"}}>
          <label htmlFor="f_img_model">Image model</label>
          <select id="f_img_model" value={imageModel}
            onChange={e=>setImageModel(e.target.value)}>
            {imageModels.map(m => (
              <option key={m.key} value={m.key}>{m.key}</option>
            ))}
          </select>
          <div style={{fontSize:".74rem", color:"var(--muted)", marginTop:".25rem"}}>
            Default comes from <code>[fal] model</code> in <code>config.ini</code>;
            picking another here only affects this run.
          </div>
        </div>
      )}
      <div className="toggle-row">
        <input type="checkbox" id="f_ow_img" checked={overwrite}
          onChange={e=>setOverwrite(e.target.checked)}/>
        <label htmlFor="f_ow_img">Overwrite existing images</label>
      </div>
      <div className="toggle-row">
        <input type="checkbox" id="f_ic" checked={ignoreCache}
          onChange={e=>setIgnoreCache(e.target.checked)}/>
        <label htmlFor="f_ic">Ignore shared cache (always call fal.ai)</label>
      </div>
      <div className="toggle-row">
        <input type="checkbox" id="f_loc_ref" checked={useLocationRef}
          onChange={e=>setUseLocationRef(e.target.checked)}/>
        <label htmlFor="f_loc_ref">Include location in reference image</label>
      </div>
      {!useLocationRef && (
        <div style={{fontSize:".76rem", color:"var(--muted)", marginTop:"-.3rem",
          paddingLeft:"1.6rem", fontStyle:"italic"}}>
          Only character art will be used as reference — the model will invent the background.
        </div>
      )}
      {isHorizontal && (
        <>
          <div className="toggle-row">
            <input type="checkbox" id="f_mosaic" checked={mosaicMode}
              onChange={e=>setMosaicMode(e.target.checked)}/>
            <label htmlFor="f_mosaic">Image-saving mode (2×2 mosaic — 1 image per 4 scenes)</label>
          </div>
          {mosaicMode && (
            <div style={{fontSize:".76rem", color:"var(--muted)", marginTop:"-.3rem",
              paddingLeft:"1.6rem", fontStyle:"italic"}}>
              Generates one 2×2 mosaic image for every 4 scenes (the intro narration keeps
              its own image) and reuses it across all four — one fal.ai call instead of four.
            </div>
          )}
        </>
      )}
    </div>
  );
}

// Shared control: annotation text size multiplier (only meaningful when grammar
// annotations are on). Renders a labelled number input.
function AnnotScaleInput({ id, value, onChange }) {
  return (
    <div className="field" style={{maxWidth:"19rem", marginTop:".1rem", marginLeft:"1.6rem"}}>
      <label htmlFor={id}>Annotation text size
        <span style={{color:"var(--muted)",fontWeight:300,marginLeft:".3rem"}}>(× scale · 1.0 = default)</span>
      </label>
      <input id={id} type="number" min="0.5" max="2.5" step="0.05"
        value={value} onChange={e=>onChange(e.target.value)}/>
      <div style={{fontSize:".74rem",color:"var(--muted)",marginTop:".25rem"}}>
        Scales the grammar subtitle text — word plus the tense/case/infinitive labels — together.
        The wrap width stays fixed, so a larger size just wraps onto more lines.
      </div>
    </div>
  );
}

// Shared control: "regenerate annotations" checkbox + hint. Forces fresh OpenAI
// annotations (ignores the cache) and re-renders the clips so the change shows.
function AnnotRegenToggle({ id, checked, onChange }) {
  return (
    <div style={{marginLeft:"1.6rem"}}>
      <div className="toggle-row">
        <input type="checkbox" id={id} checked={checked} onChange={e=>onChange(e.target.checked)}/>
        <label htmlFor={id}>Regenerate annotations (ignore cache)</label>
      </div>
      <div style={{fontSize:".74rem",color:"var(--muted)",marginTop:"-.1rem",paddingLeft:"1.6rem",fontStyle:"italic"}}>
        Re-prompts OpenAI for every sentence and re-renders the clips. Leave off to reuse
        cached annotations. To redo just one sentence, use “Redo annotation” on its card in
        the Generated Items tab.
      </div>
    </div>
  );
}

function VideoFields() {
  const { manifest, currentProject } = useApp();
  const [overwrite, setOverwrite] = useState(false);
  const [annotated, setAnnotated] = useState(false);
  const [regen,     setRegen]     = useState(false);
  const [footnote,  setFootnote]  = useState("");
  const [footHold,  setFootHold]  = useState("");
  const [fontScale, setFontScale] = useState("1.0");
  const [repeatMsg, setRepeatMsg] = useState("");
  const [repeatFs,  setRepeatFs]  = useState("");

  // Pre-fill from the settings saved on the last render (manifest.render_settings.video),
  // once per project — so re-rendering keeps your annotation/footnote/repeat choices.
  const appliedFor = React.useRef(null);
  useEffect(() => {
    if (!manifest || currentProject == null || appliedFor.current === currentProject) return;
    appliedFor.current = currentProject;
    const s = manifest.render_settings && manifest.render_settings.video;
    if (!s) return;
    if (s.annotated_subtitles != null) setAnnotated(!!s.annotated_subtitles);
    if (s.footnote != null)            setFootnote(s.footnote);
    if (s.annot_font_scale != null)    setFontScale(String(s.annot_font_scale));
    if (s.repeat_message != null)      setRepeatMsg(s.repeat_message);
    if (s.repeat_fontsize != null)     setRepeatFs(String(s.repeat_fontsize));
    if (s.footnote_hold_ms != null)    setFootHold(String(s.footnote_hold_ms / 1000));
  }, [manifest, currentProject]);

  VideoFields._getPayload = () => ({
    overwrite, annotated_subtitles: annotated, footnote,
    annot_font_scale: parseFloat(fontScale) || 1.0, regen_annotations: regen,
    // Blank = use the config default; only send when the user typed something.
    repeat_message:   repeatMsg.trim() ? repeatMsg : undefined,
    repeat_fontsize:  repeatFs.trim()  ? parseInt(repeatFs, 10) : undefined,
    // Footnote read-time entered in seconds → sent as ms. Blank = config default.
    footnote_hold_ms: footHold.trim()  ? Math.round(parseFloat(footHold) * 1000) : undefined,
  });
  return (
    <div className="fields">
      <div className="toggle-row">
        <input type="checkbox" id="f_ow_vid" checked={overwrite}
          onChange={e=>setOverwrite(e.target.checked)}/>
        <label htmlFor="f_ow_vid">Overwrite existing clips</label>
      </div>
      <div className="toggle-row">
        <input type="checkbox" id="f_ann" checked={annotated}
          onChange={e=>setAnnotated(e.target.checked)}/>
        <label htmlFor="f_ann">Grammar-annotated subtitles</label>
      </div>
      {annotated && <AnnotScaleInput id="f_ann_fs" value={fontScale} onChange={setFontScale}/>}
      {annotated && <AnnotRegenToggle id="f_ann_regen" checked={regen} onChange={setRegen}/>}
      <div className="field" style={{marginTop:".5rem"}}>
        <label>
          Footnote / Disclaimer{" "}
          <span style={{color:"var(--muted)",fontWeight:300}}>(optional — shown below narration text)</span>
        </label>
        <textarea
          rows={2}
          value={footnote}
          onChange={e => setFootnote(e.target.value)}
          placeholder="e.g. * AI-generated content. Not a substitute for professional instruction."
          style={{resize:"vertical"}}
        />
      </div>
      <div className="field" style={{maxWidth:"19rem"}}>
        <label>Footnote read time
          <span style={{color:"var(--muted)",fontWeight:300,marginLeft:".3rem"}}>(seconds, optional)</span>
        </label>
        <input type="number" min="0" max="20" step="0.5"
          value={footHold} onChange={e=>setFootHold(e.target.value)}
          placeholder="blank = config default"/>
        <div style={{fontSize:".74rem",color:"var(--muted)",marginTop:".25rem"}}>
          Extra time the scene is held after the narration so viewers can read the footnote.
          Only applies to scenes that show a footnote. 0 = no extra hold.
        </div>
      </div>

      {/* Shadowing repeat overlay — applies to the repeat scenes added in the Items tab */}
      <div style={{borderTop:"1px solid var(--border)", paddingTop:".75rem", marginTop:".25rem"}}>
        <div style={{fontSize:".82rem", fontWeight:600, marginBottom:".15rem"}}>
          Shadowing “repeat” overlay
        </div>
        <div style={{fontSize:".74rem", color:"var(--muted)", marginBottom:".5rem"}}>
          Centered message shown on the repeat scenes (add them in the <strong>Generated Items</strong> tab).
          Leave blank to use the config default. Font type lives in <code>config.ini → [repeat_prompt]</code>.
        </div>
        <div className="field-row">
          <div className="field" style={{flex:2}}>
            <label>Message <span style={{color:"var(--muted)",fontWeight:300}}>(optional)</span></label>
            <input value={repeatMsg} onChange={e=>setRepeatMsg(e.target.value)}
              placeholder="e.g. Jetzt wiederholen"/>
          </div>
          <div className="field" style={{flex:1}}>
            <label>Font size <span style={{color:"var(--muted)",fontWeight:300}}>(optional)</span></label>
            <input type="number" min="20" max="200" step="2"
              value={repeatFs} onChange={e=>setRepeatFs(e.target.value)} placeholder="e.g. 90"/>
          </div>
        </div>
      </div>
    </div>
  );
}

function AssembleFields() {
  const { manifest, currentProject } = useApp();
  const [bgAudio,       setBgAudio]       = useState("office");
  const [bgAudioTracks, setBgAudioTracks] = useState([]);
  const [bgGainDb,      setBgGainDb]      = useState("0");
  const [speedFactor,   setSpeedFactor]   = useState("1.0");
  const [overwrite,     setOverwrite]     = useState(false);
  const [brandingFile,  setBrandingFile]  = useState("");
  const [brandingMode,  setBrandingMode]  = useState("none");
  const [brandingFiles, setBrandingFiles] = useState([]);

  // Pre-fill from the settings saved on the last assemble (manifest.render_settings.assemble)
  // — once per project, so re-assembling doesn't make you re-pick background audio/branding.
  const appliedFor = React.useRef(null);
  useEffect(() => {
    if (!manifest || currentProject == null || appliedFor.current === currentProject) return;
    appliedFor.current = currentProject;
    const s = manifest.render_settings && manifest.render_settings.assemble;
    if (!s) return;
    if (s.bg_audio_name)          setBgAudio(s.bg_audio_name);
    if (s.bg_audio_gain_db != null) setBgGainDb(String(s.bg_audio_gain_db));
    if (s.speed_factor != null)   setSpeedFactor(String(s.speed_factor));
    if (s.branding_file)          setBrandingFile(s.branding_file);
    if (s.branding_mode)          setBrandingMode(s.branding_mode);
  }, [manifest, currentProject]);

  AssembleFields._getPayload = () => ({
    bg_audio_name: bgAudio,
    bg_audio_gain_db: bgGainDb !== "" ? parseFloat(bgGainDb) : 0,
    overwrite,
    speed_factor:  speedFactor !== "" ? parseFloat(speedFactor) : null,
    branding_file: brandingMode !== "none" ? brandingFile : null,
    branding_mode: brandingMode,
  });

  useEffect(() => {
    fetch("/assets/background-audio")
      .then(r => r.json())
      .then(d => {
        const tracks = Object.values(d).sort((a, b) => a.name.localeCompare(b.name));
        setBgAudioTracks(tracks);
        if (tracks.length > 0 && !tracks.find(t => t.name === bgAudio)) {
          setBgAudio(tracks[0].name);
        }
      })
      .catch(() => {});
    fetch("/assets/branding/list")
      .then(r => r.json())
      .then(d => {
        const files = d.files || [];
        setBrandingFiles(files);
        if (files.length > 0 && !brandingFile) setBrandingFile(files[0]);
      })
      .catch(() => {});
  }, []);

  const speedNum   = parseFloat(speedFactor);
  const speedValid = !isNaN(speedNum) && speedNum > 0.1 && speedNum <= 2.0;
  const speedHint  = speedValid && Math.abs(speedNum - 1.0) > 0.001
    ? speedNum < 1.0
      ? `${((1 - speedNum) * 100).toFixed(1)} % slower`
      : `${((speedNum - 1) * 100).toFixed(1)} % faster`
    : "normal speed";

  const gainNum  = parseFloat(bgGainDb);
  const gainHint = isNaN(gainNum) || Math.abs(gainNum) < 0.05
    ? "config default"
    : gainNum > 0 ? `+${gainNum.toFixed(1)} dB louder` : `${gainNum.toFixed(1)} dB quieter`;

  return (
    <div className="fields">
      <div className="field-row">
        <div className="field" style={{flex:2}}>
          <label>Background Audio</label>
          {bgAudioTracks.length > 0 ? (
            <select value={bgAudio} onChange={e=>setBgAudio(e.target.value)}>
              {bgAudioTracks.map(t => (
                <option key={t.name} value={t.name}>{t.name} — {t.description}</option>
              ))}
            </select>
          ) : (
            <input value={bgAudio} onChange={e=>setBgAudio(e.target.value)}
              placeholder="e.g. office, elevator"/>
          )}
        </div>
        <div className="field" style={{flex:1}}>
          <label>Bg Volume
            <span style={{marginLeft:".4rem", fontWeight:300, color:"var(--muted)"}}>
              ({gainHint})
            </span>
          </label>
          <input
            type="number" min="-30" max="12" step="0.5"
            value={bgGainDb}
            onChange={e => setBgGainDb(e.target.value)}
            placeholder="0"
          />
        </div>
        <div className="field" style={{flex:1}}>
          <label>Speed Factor
            <span style={{marginLeft:".4rem", fontWeight:300, color:"var(--muted)"}}>
              ({speedHint})
            </span>
          </label>
          <input
            type="number" min="0.1" max="2.0" step="0.01"
            value={speedFactor}
            onChange={e => setSpeedFactor(e.target.value)}
            style={{borderColor: speedValid ? "" : "var(--red, #f87171)"}}
          />
        </div>
      </div>

      <div style={{borderTop:"1px solid var(--border)", paddingTop:".75rem", marginTop:".25rem"}}>
        <div style={{fontSize:".82rem", fontWeight:600, marginBottom:".5rem"}}>Branding Clip</div>
        <div className="field-row">
          <div className="field" style={{flex:2}}>
            <label>File</label>
            {brandingFiles.length > 0 ? (
              <select value={brandingFile} onChange={e=>setBrandingFile(e.target.value)}>
                {brandingFiles.map(f => <option key={f} value={f}>{f}</option>)}
              </select>
            ) : (
              <input value={brandingFile} onChange={e=>setBrandingFile(e.target.value)}
                placeholder="e.g. intro.mp4"/>
            )}
          </div>
          <div className="field" style={{flex:1}}>
            <label>Position</label>
            <select value={brandingMode} onChange={e=>setBrandingMode(e.target.value)}>
              <option value="none">None</option>
              <option value="intro">Intro only</option>
              <option value="outro">Outro only</option>
              <option value="both">Intro + Outro</option>
            </select>
          </div>
        </div>
      </div>

      <div className="toggle-row">
        <input type="checkbox" id="f_ow_asm" checked={overwrite}
          onChange={e=>setOverwrite(e.target.checked)}/>
        <label htmlFor="f_ow_asm">Overwrite existing final video</label>
      </div>
    </div>
  );
}

// Common YouTube category IDs (snippet.categoryId).
const YT_CATEGORIES = [
  ["22", "People & Blogs"],
  ["27", "Education"],
  ["24", "Entertainment"],
  ["26", "Howto & Style"],
  ["1",  "Film & Animation"],
  ["10", "Music"],
  ["20", "Gaming"],
  ["23", "Comedy"],
];

function UploadFields({ projectName }) {
  const [privacy,    setPrivacy]    = useState("private");
  const [title,      setTitle]      = useState("");
  const [desc,       setDesc]       = useState("");
  const [tags,       setTags]       = useState("");
  const [category,   setCategory]   = useState("22");
  const [madeForKids,setMadeForKids]= useState(false);
  const [schedule,   setSchedule]   = useState(false);
  const [publishAt,  setPublishAt]  = useState("");   // datetime-local value (local time)
  const [metaLoaded, setMetaLoaded] = useState(false);
  const [resetMsg,   setResetMsg]   = useState("");
  const [resetting,  setResetting]  = useState(false);

  // Pre-fill the editable fields with the exact metadata that would be sent,
  // so the user can preview and tweak the title/description/tags before upload.
  useEffect(() => {
    if (!projectName) return;
    fetch(`/projects/${projectName}/upload_meta`)
      .then(r => r.json())
      .then(d => {
        if (d.error) return;
        setTitle(d.title || "");
        setDesc(d.description || "");
        setTags((d.tags || []).join(", "));
        setMetaLoaded(true);
      })
      .catch(() => {});
  }, [projectName]);

  UploadFields._getPayload = () => ({
    privacy,
    title,
    description: desc,
    tags,
    category_id: category,
    made_for_kids: madeForKids,
    // Convert the local datetime-local value to an RFC 3339 UTC string.
    publish_at: schedule && publishAt ? new Date(publishAt).toISOString() : "",
  });

  async function resetAuth() {
    setResetting(true);
    setResetMsg("");
    try {
      const r = await fetch("/auth/youtube/reset", { method: "POST" });
      const d = await r.json();
      setResetMsg(d.message || d.error || "Done");
    } catch(e) {
      setResetMsg("Request failed: " + e.message);
    } finally {
      setResetting(false);
    }
  }

  return (
    <div className="fields">
      <div className="field">
        <label>Title <span style={{color:"var(--muted)",fontWeight:300}}>
          {metaLoaded ? "(pre-filled — edit before upload)" : "(loading…)"}</span></label>
        <input value={title} onChange={e=>setTitle(e.target.value)}
          placeholder="Loading from manifest…"/>
      </div>
      <div className="field">
        <label>Description <span style={{color:"var(--muted)",fontWeight:300}}>
          {metaLoaded ? "(pre-filled — edit before upload)" : "(loading…)"}</span></label>
        <textarea rows={6} value={desc} onChange={e=>setDesc(e.target.value)}
          placeholder="Loading from manifest…"/>
      </div>
      <div className="field">
        <label>Tags <span style={{color:"var(--muted)",fontWeight:300}}>(comma-separated)</span></label>
        <textarea rows={2} value={tags} onChange={e=>setTags(e.target.value)}
          placeholder="german, deutschlernen, shorts"/>
      </div>

      <div className="field-row">
        <div className="field">
          <label>Privacy</label>
          <select value={privacy} onChange={e=>setPrivacy(e.target.value)} disabled={schedule}>
            <option value="private">Private</option>
            <option value="unlisted">Unlisted</option>
            <option value="public">Public</option>
          </select>
        </div>
        <div className="field">
          <label>Category</label>
          <select value={category} onChange={e=>setCategory(e.target.value)}>
            {YT_CATEGORIES.map(([id, label]) =>
              <option key={id} value={id}>{label}</option>)}
          </select>
        </div>
      </div>

      <div className="toggle-row">
        <input type="checkbox" id="f_yt_kids" checked={madeForKids}
          onChange={e=>setMadeForKids(e.target.checked)}/>
        <label htmlFor="f_yt_kids">Made for kids</label>
      </div>

      <div className="toggle-row">
        <input type="checkbox" id="f_yt_sched" checked={schedule}
          onChange={e=>setSchedule(e.target.checked)}/>
        <label htmlFor="f_yt_sched">Schedule release (publish later automatically)</label>
      </div>
      {schedule && (
        <div className="field">
          <label>Release date &amp; time <span style={{color:"var(--muted)",fontWeight:300}}>(your local time)</span></label>
          <input type="datetime-local" value={publishAt}
            onChange={e=>setPublishAt(e.target.value)}/>
          <div style={{fontSize:".76rem", color:"var(--muted)", marginTop:".3rem"}}>
            The video uploads as <strong>Private</strong> and YouTube flips it to public at this time.
          </div>
        </div>
      )}

      <div style={{borderTop:"1px solid var(--border)", paddingTop:".75rem", marginTop:".25rem"}}>
        <div style={{fontSize:".78rem", color:"var(--muted)", marginBottom:".5rem"}}>
          If you see an <strong>invalid_grant</strong> error, the saved login token has expired.
          Click below to clear it — the next upload will open a browser to re-authenticate.
        </div>
        <button
          className="btn-cancel"
          onClick={resetAuth}
          disabled={resetting}
          style={{fontSize:".8rem"}}
        >
          {resetting ? "Clearing…" : "Reset YouTube Login"}
        </button>
        {resetMsg && (
          <div style={{marginTop:".4rem", fontSize:".78rem", color:"var(--muted)"}}>
            {resetMsg}
          </div>
        )}
      </div>
    </div>
  );
}

// ── reading_together step fields ───────────────────────────────────────────────

function ReadingBuildFields() {
  const [maxWords, setMaxWords] = React.useState("16");
  ReadingBuildFields._getPayload = () => ({
    max_words: maxWords !== "" ? parseInt(maxWords, 10) : null,
  });
  return (
    <div className="fields">
      <div className="field"><label>Max words / sentence</label>
        <input type="number" min="5" max="40" value={maxWords} onChange={e=>setMaxWords(e.target.value)}/></div>
      <div style={{fontSize:".8rem",color:"var(--muted)"}}>
        Modernizes the pasted story, splits it into sentences, casts characters, and plans one illustration per sentence.
        How many sentences go into each vertical part is chosen later, in “Assemble Parts + Long”.
      </div>
    </div>
  );
}

function ReadingCastFields() {
  const { manifest }              = useApp();
  const [regen, setRegen]         = React.useState(false);
  const [reanalyze, setReanalyze] = React.useState(true);
  const [allChars, setAllChars]   = React.useState({});

  const reading    = manifest?.generation_config?.reading || {};
  const storyChars = reading.characters || [];
  const [mapping, setMapping] = React.useState(() => ({ ...(reading.cast_mapping || {}) }));

  // Existing characters the user can cast in a role (exclude the Narrator and the
  // auto-generated rt_ story assets).
  React.useEffect(() => {
    fetch("/assets/characters").then(r => r.json()).then(d => setAllChars(d || {})).catch(() => {});
  }, []);
  const existingKeys = Object.keys(allChars)
    .filter(k => k !== "Narrator" && !k.startsWith("rt_"))
    .sort((a, b) => a.localeCompare(b));

  ReadingCastFields._getPayload = () => ({ regenerate: regen, reanalyze, cast_mapping: mapping });

  const setRole = (name, key) => setMapping(m => {
    const next = { ...m };
    if (key) next[name] = key; else delete next[name];
    return next;
  });

  return (
    <div className="fields">
      <div className="toggle-row">
        <input type="checkbox" id="f_rt_reanalyze" checked={reanalyze} onChange={e=>setReanalyze(e.target.checked)}/>
        <label htmlFor="f_rt_reanalyze">Re-detect characters from the story (merge — keeps existing)</label>
      </div>
      <div className="toggle-row">
        <input type="checkbox" id="f_rt_regen" checked={regen} onChange={e=>setRegen(e.target.checked)}/>
        <label htmlFor="f_rt_regen">Regenerate reference images (overwrites existing art)</label>
      </div>

      {/* Cast your own characters in the story's roles */}
      <div style={{marginTop:".3rem"}}>
        <div style={{fontSize:".82rem", fontWeight:600, marginBottom:".35rem"}}>Cast characters in roles</div>
        {storyChars.length === 0 ? (
          <div style={{fontSize:".78rem", color:"var(--muted)"}}>
            No story characters yet — run <strong>Build Reading Source</strong> first, then re-open this step.
          </div>
        ) : (
          <div style={{display:"flex", flexDirection:"column", gap:".4rem"}}>
            {storyChars.map(c => (
              <div key={c.name} style={{display:"flex", alignItems:"center", gap:".5rem"}}>
                <div style={{minWidth:"120px", fontSize:".8rem"}}>
                  <span style={{fontWeight:600}}>{c.name}</span>
                  <span style={{color:"var(--muted)"}}> · {c.kind}</span>
                </div>
                <select value={mapping[c.name] || ""} onChange={e => setRole(c.name, e.target.value)}
                  style={{flex:1, padding:".3rem .4rem", borderRadius:"5px",
                    border:"1px solid var(--border)", background:"var(--surface-2)", color:"var(--fg)"}}>
                  <option value="">Auto-generate a new character</option>
                  {existingKeys.map(k => (
                    <option key={k} value={k}>{(allChars[k] && allChars[k].name) || k}</option>
                  ))}
                </select>
              </div>
            ))}
          </div>
        )}
        <div style={{fontSize:".75rem", color:"var(--muted)", marginTop:".35rem", fontStyle:"italic"}}>
          Pick one of your own characters to play a role, or leave it on “Auto-generate”. Mapped roles use that
          character’s existing reference art — no new image is created for them.
        </div>
      </div>

      <div style={{fontSize:".8rem",color:"var(--muted)"}}>
        Creates one reusable reference image per auto-generated story character — humans and animals. Safe to
        re-run: newly found characters are added and existing ones (and their images) are kept, unless you tick
        “Regenerate reference images”.
      </div>
    </div>
  );
}

function ReadingVideoFields() {
  const [overwrite, setOverwrite] = React.useState(false);
  const [annotated, setAnnotated] = React.useState(true);
  const [regen,     setRegen]     = React.useState(false);
  const [fontScale, setFontScale] = React.useState("1.0");
  ReadingVideoFields._getPayload = () => ({
    overwrite, annotated_subtitles: annotated,
    annot_font_scale: parseFloat(fontScale) || 1.0, regen_annotations: regen,
  });
  return (
    <div className="fields">
      <div className="toggle-row">
        <input type="checkbox" id="f_rt_ow" checked={overwrite} onChange={e=>setOverwrite(e.target.checked)}/>
        <label htmlFor="f_rt_ow">Overwrite existing clips</label>
      </div>
      <div className="toggle-row">
        <input type="checkbox" id="f_rt_ann" checked={annotated} onChange={e=>setAnnotated(e.target.checked)}/>
        <label htmlFor="f_rt_ann">Grammar-annotated subtitles</label>
      </div>
      {annotated && <AnnotScaleInput id="f_rt_fs" value={fontScale} onChange={setFontScale}/>}
      {annotated && <AnnotRegenToggle id="f_rt_regen" checked={regen} onChange={setRegen}/>}
    </div>
  );
}

function ReadingHorizFields() {
  const [overwrite, setOverwrite] = React.useState(false);
  const [annotated, setAnnotated] = React.useState(true);
  const [regen,     setRegen]     = React.useState(false);
  const [fontScale, setFontScale] = React.useState("1.0");
  ReadingHorizFields._getPayload = () => ({
    overwrite, annotated_subtitles: annotated, format_override: "horizontal", out_subdir: "h",
    annot_font_scale: parseFloat(fontScale) || 1.0, regen_annotations: regen,
  });
  return (
    <div className="fields">
      <div style={{fontSize:".8rem",color:"var(--muted)",marginBottom:".4rem"}}>
        Renders a 16:9 copy of every scene into <code>videos/h/</code> for the long video.
      </div>
      <div className="toggle-row">
        <input type="checkbox" id="f_rt_owh" checked={overwrite} onChange={e=>setOverwrite(e.target.checked)}/>
        <label htmlFor="f_rt_owh">Overwrite existing horizontal clips</label>
      </div>
      <div className="toggle-row">
        <input type="checkbox" id="f_rt_annh" checked={annotated} onChange={e=>setAnnotated(e.target.checked)}/>
        <label htmlFor="f_rt_annh">Grammar-annotated subtitles</label>
      </div>
      {annotated && <AnnotScaleInput id="f_rt_fsh" value={fontScale} onChange={setFontScale}/>}
      {annotated && <AnnotRegenToggle id="f_rt_regenh" checked={regen} onChange={setRegen}/>}
    </div>
  );
}

function ReadingAssembleFields() {
  const [bg, setBg]             = React.useState("office");
  const [bgGainDb, setBgGainDb] = React.useState("0");
  const [overwrite, setOverwrite] = React.useState(false);
  const [parts, setParts]       = React.useState(true);
  const [long, setLong]         = React.useState(true);
  const [perPart, setPerPart]   = React.useState("6");
  const [speedFactor, setSpeedFactor] = React.useState("1.0");
  const [brandingOn, setBrandingOn]     = React.useState(false);
  const [brandingFile, setBrandingFile] = React.useState("");
  const [brandingFiles, setBrandingFiles] = React.useState([]);
  ReadingAssembleFields._getPayload = () => ({
    bg_audio_name: bg, overwrite, make_parts: parts, make_long: long,
    bg_audio_gain_db: bgGainDb !== "" ? parseFloat(bgGainDb) : 0,
    branding_mode: brandingOn && brandingFile ? "intro" : "none",
    branding_file: brandingOn ? brandingFile : null,
    per_part: perPart !== "" ? parseInt(perPart, 10) : null,
    speed_factor: speedFactor !== "" ? parseFloat(speedFactor) : null,
  });

  React.useEffect(() => {
    fetch("/assets/branding/list")
      .then(r => r.json())
      .then(d => {
        const files = d.files || [];
        setBrandingFiles(files);
        if (files.length > 0 && !brandingFile) setBrandingFile(files[0]);
      })
      .catch(() => {});
  }, []);

  const speedNum   = parseFloat(speedFactor);
  const speedValid = !isNaN(speedNum) && speedNum > 0.1 && speedNum <= 2.0;
  const speedHint  = speedValid && Math.abs(speedNum - 1.0) > 0.001
    ? speedNum < 1.0
      ? `${((1 - speedNum) * 100).toFixed(1)} % slower`
      : `${((speedNum - 1) * 100).toFixed(1)} % faster`
    : "normal speed";

  const rtGainNum  = parseFloat(bgGainDb);
  const rtGainHint = isNaN(rtGainNum) || Math.abs(rtGainNum) < 0.05
    ? "config default"
    : rtGainNum > 0 ? `+${rtGainNum.toFixed(1)} dB louder` : `${rtGainNum.toFixed(1)} dB quieter`;

  return (
    <div className="fields">
      <div className="field-row">
        <div className="field"><label>Background Audio</label>
          <input value={bg} onChange={e=>setBg(e.target.value)} placeholder="e.g. office, park"/></div>
        <div className="field"><label>Bg Volume
            <span style={{marginLeft:".4rem", fontWeight:300, color:"var(--muted)"}}>
              ({rtGainHint})
            </span>
          </label>
          <input type="number" min="-30" max="12" step="0.5" value={bgGainDb}
            onChange={e=>setBgGainDb(e.target.value)} placeholder="0"/></div>
        <div className="field"><label>Sentences per vertical part</label>
          <input type="number" min="1" max="20" value={perPart} onChange={e=>setPerPart(e.target.value)}/></div>
      </div>
      <div className="field-row">
        <div className="field"><label>Speed Factor
            <span style={{marginLeft:".4rem", fontWeight:300, color:"var(--muted)"}}>
              ({speedHint})
            </span>
          </label>
          <input
            type="number" min="0.1" max="2.0" step="0.01"
            value={speedFactor}
            onChange={e => setSpeedFactor(e.target.value)}
            style={{borderColor: speedValid ? "" : "var(--red, #f87171)"}}
          />
          <div style={{fontSize:".76rem", color:"var(--muted)", marginTop:".25rem", fontStyle:"italic"}}>
            Applies to both vertical parts and the long video. 0.95 = 5 % slower.
          </div>
        </div>
      </div>
      <div className="toggle-row">
        <input type="checkbox" id="f_rt_parts" checked={parts} onChange={e=>setParts(e.target.checked)}/>
        <label htmlFor="f_rt_parts">Build vertical parts (6 sentences each)</label>
      </div>
      <div className="toggle-row">
        <input type="checkbox" id="f_rt_long" checked={long} onChange={e=>setLong(e.target.checked)}/>
        <label htmlFor="f_rt_long">Build long horizontal video</label>
      </div>

      <div style={{borderTop:"1px solid var(--border)", paddingTop:".75rem", marginTop:".25rem"}}>
        <div className="toggle-row">
          <input type="checkbox" id="f_rt_brand" checked={brandingOn} onChange={e=>setBrandingOn(e.target.checked)}/>
          <label htmlFor="f_rt_brand">Add branding intro (vertical parts + long video)</label>
        </div>
        {brandingOn && (
          <div className="field" style={{marginTop:".4rem", marginLeft:"1.6rem", maxWidth:"22rem"}}>
            <label>Branding file</label>
            {brandingFiles.length > 0 ? (
              <select value={brandingFile} onChange={e=>setBrandingFile(e.target.value)}>
                {brandingFiles.map(f => <option key={f} value={f}>{f}</option>)}
              </select>
            ) : (
              <input value={brandingFile} onChange={e=>setBrandingFile(e.target.value)}
                placeholder="e.g. intro.mp4"/>
            )}
            <div style={{fontSize:".74rem", color:"var(--muted)", marginTop:".25rem", fontStyle:"italic"}}>
              Prepended as an intro to every vertical part and the long video.
            </div>
          </div>
        )}
      </div>

      <div className="toggle-row">
        <input type="checkbox" id="f_rt_owa" checked={overwrite} onChange={e=>setOverwrite(e.target.checked)}/>
        <label htmlFor="f_rt_owa">Overwrite existing outputs</label>
      </div>
    </div>
  );
}

// ── promotional step fields ─────────────────────────────────────────────────────

function PromoBuildFields() {
  const { manifest, characters } = useApp();
  const gen   = manifest?.generation_config || {};
  const promo = gen.promotional || {};
  const [character, setCharacter] = React.useState(promo.character || (gen.characters || [])[0] || "");
  const [situation, setSituation] = React.useState(promo.situation || gen.provided_context || "");
  const [text,      setText]      = React.useState(promo.text || "");

  PromoBuildFields._getPayload = () => ({ character, situation, text });

  return (
    <div className="fields">
      <div className="field">
        <label>Character</label>
        <select value={character} onChange={e=>setCharacter(e.target.value)}>
          <option value="">— select —</option>
          {characters.filter(c => c !== "Narrator").map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div className="field">
        <label>Image situation
          <span style={{color:"var(--muted)",fontWeight:300,marginLeft:".3rem"}}>(what the still shows)</span>
        </label>
        <textarea rows={3} value={situation} onChange={e=>setSituation(e.target.value)}
          placeholder="e.g. standing in a cozy café holding a coffee, smiling warmly at the camera"/>
      </div>
      <div className="field">
        <label>Text to say
          <span style={{color:"var(--muted)",fontWeight:300,marginLeft:".3rem"}}>(spoken + subtitle)</span>
        </label>
        <textarea rows={3} value={text} onChange={e=>setText(e.target.value)}
          placeholder="e.g. Willst du dein Deutsch verbessern? Schau dir mein neues Video an!"/>
      </div>
      <div style={{fontSize:".78rem",color:"var(--muted)"}}>
        Builds one vertical 9:16 scene: the character image, their voice, and the subtitle.
        No intro and no horizontal version.
      </div>
    </div>
  );
}

function PromoVideoFields() {
  const [overwrite, setOverwrite] = React.useState(false);
  // Plain subtitles (no grammar annotation) for a promo line.
  PromoVideoFields._getPayload = () => ({ overwrite, annotated_subtitles: false });
  return (
    <div className="fields">
      <div className="toggle-row">
        <input type="checkbox" id="f_promo_ow" checked={overwrite} onChange={e=>setOverwrite(e.target.checked)}/>
        <label htmlFor="f_promo_ow">Overwrite existing clip</label>
      </div>
    </div>
  );
}

// ── GPT manifest review ────────────────────────────────────────────────────────

const SEV_STYLE = {
  error:      { color:"var(--red, #f87171)",   label:"Error"      },
  warning:    { color:"var(--amber, #fbbf24)", label:"Warning"    },
  suggestion: { color:"var(--muted)",          label:"Suggestion" },
};

// Rule id → short human label + which group it belongs to (for display only).
const RULE_LABELS = {
  grammar:        "Grammar",
  spelling:       "Spelling",
  highlight:      "Highlight missing",
  highlight_qual: "Highlight quality",
  level:          "Level fit",
  coherence:      "Coherence",
  register:       "Register",
  speaker_flow:   "Speaker flow",
  visual_detail:  "Visual detail",
  visual_match:   "Visual match",
  narration:      "Narration",
  length:         "Length",
  other:          "Other",
};

const FIELD_LABELS = { subtitle_text: "subtitle", scene_visual: "visual" };

function ReviewFields({ projectName }) {
  const { manifest, reloadManifest, toast } = useApp();
  const review = manifest?.manifest_review || null;
  const [prompt, setPrompt]     = React.useState("");
  const [applying, setApplying] = React.useState(null);   // null | "all" | "<key>"

  ReviewFields._getPayload = () => ({
    prompt_override: prompt.trim() || null,
  });

  const counts   = review?.counts || {};
  const issues   = review?.issues || [];
  const remaining = issues.filter(i => i.fixed && !i.applied).length;

  async function applyFixes(keys, tag) {
    setApplying(tag);
    try {
      const d = await apiPost(`/projects/${projectName}/review/apply`,
        keys ? { keys } : {});
      toast("Fixes applied", `${d.applied} correction${d.applied !== 1 ? "s" : ""} written to the manifest.`, "ok");
      await reloadManifest(projectName);
    } catch (e) {
      toast("Error", e.message, "err");
    } finally {
      setApplying(null);
    }
  }

  return (
    <div className="fields">
      <div style={{fontSize:".84rem", color:"var(--muted)", marginBottom:".2rem"}}>
        GPT checks every narration, dialog, and repetition line against the review
        rules (grammar, spelling, vocabulary highlighting, CEFR level, coherence,
        register, speaker flow, and the visual prompts). It is an independent
        pass — it never sees the prompt used to generate the script. Run it after
        <strong> Generate Script</strong> and before audio/images. Fixes are only
        written when you click <strong>Apply</strong>. Requires <code>OPENAI_API_KEY</code>.
      </div>

      <div className="prompt-section">
        <div className="prompt-header">
          <span>What should GPT focus on? (optional)</span>
        </div>
        <textarea className="prompt-editor" value={prompt}
          onChange={e=>setPrompt(e.target.value)}
          placeholder="Leave blank to run the full rule set. Or narrow it, e.g. 'Only check case endings and Sie/du consistency.'"/>
      </div>

      {review && (
        <div style={{borderTop:"1px solid var(--border)", paddingTop:".6rem", marginTop:".4rem"}}>
          <div style={{fontSize:".78rem", color:"var(--muted)", marginBottom:".4rem"}}>
            Last reviewed {review.reviewed_at} · {review.model} · level {review.level} ·{" "}
            {review.lines_reviewed} lines
          </div>
          <div style={{display:"flex", gap:".5rem", marginBottom:".5rem", flexWrap:"wrap", alignItems:"center"}}>
            {["error","warning","suggestion"].map(sev => (
              <span key={sev} style={{fontSize:".76rem", fontWeight:600,
                color: SEV_STYLE[sev].color}}>
                {counts[sev] || 0} {SEV_STYLE[sev].label.toLowerCase()}
                {(counts[sev] || 0) !== 1 ? "s" : ""}
              </span>
            ))}
            {remaining > 0 && (
              <button className="btn-primary" style={{marginLeft:"auto", fontSize:".78rem", padding:".3rem .7rem"}}
                disabled={!!applying}
                onClick={() => applyFixes(null, "all")}>
                {applying === "all" ? "Applying…" : `Apply all ${remaining} fix${remaining !== 1 ? "es" : ""}`}
              </button>
            )}
          </div>
          {review.summary && (
            <div style={{fontSize:".82rem", marginBottom:".6rem", lineHeight:1.4}}>
              {review.summary}
            </div>
          )}
          {issues.length === 0 ? (
            <div style={{fontSize:".82rem", color:"var(--green, #4ade80)"}}>
              ✓ No issues found.
            </div>
          ) : (
            <div style={{display:"flex", flexDirection:"column", gap:".4rem"}}>
              {issues.map((it, i) => {
                const sev = SEV_STYLE[it.severity] || SEV_STYLE.suggestion;
                const key = `${it.scene_id}::${it.field}`;
                const ruleLabel  = RULE_LABELS[it.rule] || it.rule;
                const fieldLabel = FIELD_LABELS[it.field];
                return (
                  <div key={i} style={{borderLeft:`3px solid ${sev.color}`,
                    padding:".35rem .6rem", background:"var(--surface-2)",
                    borderRadius:"4px", opacity: it.applied ? 0.6 : 1}}>
                    <div style={{fontSize:".72rem", color:sev.color, fontWeight:600,
                      textTransform:"uppercase", letterSpacing:".02em"}}>
                      {sev.label} · {ruleLabel} · {it.scene_id}
                      {fieldLabel ? ` · ${fieldLabel}` : ""}
                    </div>
                    {it.quote && (
                      <div style={{fontSize:".82rem", fontStyle:"italic", margin:".2rem 0"}}>
                        “{it.quote}”
                      </div>
                    )}
                    <div style={{fontSize:".8rem"}}>{it.issue}</div>
                    {it.fixed && (
                      <div style={{display:"flex", alignItems:"flex-start", gap:".5rem", marginTop:".3rem"}}>
                        <div style={{fontSize:".8rem", flex:1}}>
                          <span style={{color:"var(--muted)"}}>→ </span>
                          <span style={{color:"var(--green, #4ade80)"}}>{it.fixed}</span>
                        </div>
                        {it.applied ? (
                          <span style={{fontSize:".74rem", color:"var(--green, #4ade80)", whiteSpace:"nowrap"}}>✓ Applied</span>
                        ) : (
                          <button className="btn-ghost" style={{fontSize:".74rem", padding:".2rem .55rem", whiteSpace:"nowrap"}}
                            disabled={!!applying}
                            onClick={() => applyFixes([key], key)}>
                            {applying === key ? "…" : "Apply"}
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Step definitions ───────────────────────────────────────────────────────────

function makeSteps(projectName, manifest) {
  const videoFormat = (manifest?.video_info?.video_format) || "vertical";
  const igDisabled  = videoFormat === "horizontal"
    ? "Instagram only supports vertical 9:16 Reels. Export to YouTube instead."
    : null;

  const ptype = manifest?.project_metadata?.project_type_key;
  if (ptype === "reading_together") {
    return [
      { id:"reading_build", num:1, title:"Build Reading Source",
        desc:"Modernize the story, split sentences, cast characters, plan illustrations.",
        Fields: ReadingBuildFields, payload:()=>ReadingBuildFields._getPayload?.()||{},
        endpoint:n=>`/projects/${n}/run/reading_build` },
      { id:"audio", num:2, title:"Generate Audio", desc:"ElevenLabs narrates each sentence.",
        Fields: AudioFields, payload:()=>AudioFields._getPayload?.()||{}, endpoint:n=>`/projects/${n}/run/audio` },
      { id:"reading_cast", num:3, title:"Cast Characters",
        desc:"Create one reusable reference image per story character (animals included).",
        Fields: ReadingCastFields, payload:()=>ReadingCastFields._getPayload?.()||{},
        endpoint:n=>`/projects/${n}/run/reading_cast` },
      { id:"images", num:4, title:"Generate Images", desc:"fal.ai illustrates each sentence.",
        Fields: ImagesFields, payload:()=>ImagesFields._getPayload?.()||{},
        endpoint:n=>`/projects/${n}/run/images` },
      { id:"video", num:5, title:"Render Vertical Clips", desc:"One 9:16 clip per sentence (annotated).",
        Fields: ReadingVideoFields, payload:()=>ReadingVideoFields._getPayload?.()||{},
        endpoint:n=>`/projects/${n}/run/video` },
      { id:"video_h", num:6, title:"Render Horizontal Clips", desc:"16:9 copies into videos/h/ for the long video.",
        Fields: ReadingHorizFields, payload:()=>ReadingHorizFields._getPayload?.()||{},
        endpoint:n=>`/projects/${n}/run/video` },
      { id:"reading_assemble", num:7, title:"Assemble Parts + Long",
        desc:"final_part1..N.mp4 (vertical) + final_long.mp4 (horizontal).",
        Fields: ReadingAssembleFields, payload:()=>ReadingAssembleFields._getPayload?.()||{},
        endpoint:n=>`/projects/${n}/run/reading_assemble` },
      { id:"upload", num:8, title:"Upload to YouTube", desc:"Metadata auto-read from manifest.",
        Fields: UploadFields, payload:()=>UploadFields._getPayload?.()||{},
        endpoint:n=>`/projects/${n}/run/upload` },
    ];
  }

  if (ptype === "promotional") {
    return [
      { id:"promo_build", num:1, title:"Build Promotional Scene",
        desc:"Pick the character, describe the image, and write the line they say.",
        Fields: PromoBuildFields, payload:()=>PromoBuildFields._getPayload?.()||{},
        endpoint:n=>`/projects/${n}/run/promo_build` },
      { id:"audio", num:2, title:"Generate Audio", desc:"ElevenLabs voices the line.",
        Fields: AudioFields, payload:()=>AudioFields._getPayload?.()||{},
        endpoint:n=>`/projects/${n}/run/audio` },
      { id:"images", num:3, title:"Generate Image", desc:"fal.ai illustrates the character in the scene.",
        Fields: ImagesFields, payload:()=>ImagesFields._getPayload?.()||{},
        endpoint:n=>`/projects/${n}/run/images` },
      { id:"video", num:4, title:"Render Video", desc:"Still image + voice + subtitle (vertical 9:16).",
        Fields: PromoVideoFields, payload:()=>PromoVideoFields._getPayload?.()||{},
        endpoint:n=>`/projects/${n}/run/video` },
      { id:"assemble", num:5, title:"Assemble Final Video",
        desc:"Optional background music; no intro.",
        Fields: AssembleFields, payload:()=>AssembleFields._getPayload?.()||{},
        endpoint:n=>`/projects/${n}/run/assemble` },
    ];
  }

  return [
    {
      id:"script", num:1,
      title:"Generate Script",
      desc:"GPT writes dialogue, narration, and repetitions.",
      Fields: (props) => <ScriptFields projectName={projectName} {...props}/>,
      payload: () => ScriptFields._getPayload?.() || {},
      endpoint: n => `/projects/${n}/run/script`,
    },
    {
      id:"review", num:2,
      title:"Review Script (GPT)",
      desc:"GPT proofreads the German script for grammar, naturalness, and level.",
      Fields: ReviewFields,
      payload: () => ReviewFields._getPayload?.() || {},
      endpoint: n => `/projects/${n}/run/review`,
    },
    {
      id:"audio", num:3,
      title:"Generate Audio",
      desc:"ElevenLabs TTS for narration, dialogue, and repetitions.",
      Fields: AudioFields,
      payload: () => AudioFields._getPayload?.() || {},
      endpoint: n => `/projects/${n}/run/audio`,
    },
    {
      id:"images", num:4,
      title:"Generate Images",
      desc:"fal.ai generates scene images for every dialogue line.",
      Fields: ImagesFields,
      payload: () => ImagesFields._getPayload?.() || {},
      endpoint: n => `/projects/${n}/run/images`,
    },
    {
      id:"video", num:5,
      title:"Render Scene Clips",
      desc:"MoviePy renders one .mp4 per scene.",
      Fields: VideoFields,
      payload: () => VideoFields._getPayload?.() || {},
      endpoint: n => `/projects/${n}/run/video`,
    },
    {
      id:"assemble", num:6,
      title:"Assemble Final Video",
      desc:"Concatenates clips, adds background music and branding.",
      Fields: AssembleFields,
      payload: () => AssembleFields._getPayload?.() || {},
      endpoint: n => `/projects/${n}/run/assemble`,
    },
    {
      id:"upload", num:7,
      title:"Upload to YouTube",
      desc:"Metadata auto-read from manifest.",
      Fields: UploadFields,
      payload: () => UploadFields._getPayload?.() || {},
      endpoint: n => `/projects/${n}/run/upload`,
    },
    {
      id:"upload_instagram", num:8,
      title:"Upload to Instagram",
      desc:"Publish as a Reel via Instagram Graph API.",
      Fields: InstagramUploadFields,
      payload: () => InstagramUploadFields._getPayload?.() || {},
      endpoint: n => `/projects/${n}/run/upload_instagram`,
      disabledReason: igDisabled,
    },
    {
      id:"upload_facebook", num:9,
      title:"Upload to Facebook",
      desc:"Publish to a Facebook Page (feed video or Reel).",
      Fields: FacebookUploadFields,
      payload: () => FacebookUploadFields._getPayload?.() || {},
      endpoint: n => `/projects/${n}/run/upload_facebook`,
    },
  ];
}

function PipelineTab({ projectName }) {
  const { manifest } = useApp();
  const steps = makeSteps(projectName, manifest);
  return (
    <div className="pipeline">
      {steps.map(step => (
        <StepCard key={step.id} step={step} projectName={projectName}/>
      ))}
    </div>
  );
}

// ── Connection banner (shared by IG/FB upload steps) ──────────────────────────
// Credential setup now lives on the Connections page; each upload step only shows
// whether the connection is ready and links there when it isn't.

function ConnectionBanner({ configured, connectedText }) {
  if (configured == null) return null;  // status not loaded yet
  return (
    <div style={{
      padding: ".5rem .75rem", borderRadius: 6, marginBottom: ".75rem", fontSize: ".8rem",
      background: configured ? "rgba(74,222,128,.12)" : "rgba(248,113,113,.12)",
      color: configured ? "var(--green, #4ade80)" : "var(--red, #f87171)",
      border: `1px solid ${configured ? "rgba(74,222,128,.3)" : "rgba(248,113,113,.3)"}`,
    }}>
      {configured
        ? connectedText
        : "Not connected — set this up on the Connections page (top nav) before uploading."}
    </div>
  );
}

// ── Instagram Upload Fields ───────────────────────────────────────────────────

function InstagramUploadFields() {
  const [caption,     setCaption]     = React.useState("");
  const [shareToFeed, setShareToFeed] = React.useState(true);
  const [coverSec,    setCoverSec]    = React.useState("");   // cover-frame time in seconds
  const [status,      setStatus]      = React.useState(null);

  InstagramUploadFields._getPayload = () => ({
    caption,
    share_to_feed: shareToFeed,
    // Seconds in the UI → milliseconds for the API (thumb_offset). Blank = default.
    thumb_offset_ms: coverSec !== "" ? Math.round(parseFloat(coverSec) * 1000) : "",
  });

  React.useEffect(() => {
    fetch("/auth/instagram/status").then(r => r.json()).then(setStatus).catch(() => {});
  }, []);

  const configured = status ? !!status.configured : null;

  return (
    <div className="fields">
      <ConnectionBanner
        configured={configured}
        connectedText={status
          ? `Connected — token valid for ${status.days_left} more day${status.days_left !== 1 ? "s" : ""}`
          : ""} />
      <div className="field">
        <label>Caption Override <span style={{color:"var(--muted)",fontWeight:300}}>(optional)</span></label>
        <textarea rows={3} value={caption} onChange={e=>setCaption(e.target.value)}
          placeholder="Leave blank to auto-generate from manifest"/>
      </div>
      <div className="toggle-row">
        <input type="checkbox" id="f_ig_feed" checked={shareToFeed}
          onChange={e=>setShareToFeed(e.target.checked)}/>
        <label htmlFor="f_ig_feed">Share Reel to Feed</label>
      </div>
      <div className="field">
        <label>Cover frame <span style={{color:"var(--muted)",fontWeight:300}}>(seconds into the video — optional)</span></label>
        <input type="number" min="0" step="0.1" value={coverSec}
          onChange={e=>setCoverSec(e.target.value)}
          placeholder="Blank = auto (first clean frame)"/>
        <div style={{fontSize:".76rem", color:"var(--muted)", marginTop:".3rem"}}>
          Instagram grabs the frame at this time as the Reel thumbnail. Left blank, it
          defaults to the cover frame auto-detected during assembly (the first scene
          image shown without a subtitle).
        </div>
      </div>
    </div>
  );
}

// ── Facebook Upload Fields ────────────────────────────────────────────────────

function FacebookUploadFields() {
  const [caption,   setCaption]   = React.useState("");
  const [asReel,    setAsReel]    = React.useState(false);
  const [coverSec,  setCoverSec]  = React.useState("");   // feed-video cover frame (seconds)
  const [schedule,  setSchedule]  = React.useState(false);
  const [publishAt, setPublishAt] = React.useState("");   // datetime-local (local time)
  const [status,    setStatus]    = React.useState(null);

  FacebookUploadFields._getPayload = () => ({
    caption,
    as_reel: asReel,
    // Cover frame only applies to feed videos (Reels have no thumbnail param).
    thumb_offset_ms: (!asReel && coverSec !== "") ? Math.round(parseFloat(coverSec) * 1000) : "",
    // datetime-local is local time → ISO 8601 UTC for the backend.
    publish_at: schedule && publishAt ? new Date(publishAt).toISOString() : "",
  });

  React.useEffect(() => {
    fetch("/auth/facebook/status").then(r => r.json()).then(setStatus).catch(() => {});
  }, []);

  const configured = status ? !!status.configured : null;

  return (
    <div className="fields">
      <ConnectionBanner
        configured={configured}
        connectedText={status ? `Connected to Page ${status.page_name || status.page_id}` : ""} />
      <div className="field">
        <label>Caption / Description <span style={{color:"var(--muted)",fontWeight:300}}>(optional)</span></label>
        <textarea rows={3} value={caption} onChange={e=>setCaption(e.target.value)}
          placeholder="Leave blank to auto-generate from manifest"/>
      </div>
      <div className="toggle-row">
        <input type="checkbox" id="f_fb_reel" checked={asReel}
          onChange={e=>setAsReel(e.target.checked)}/>
        <label htmlFor="f_fb_reel">Publish as a Reel (vertical 9:16)</label>
      </div>

      {/* Cover frame — feed videos only; Facebook Reels have no thumbnail parameter. */}
      {!asReel && (
        <div className="field">
          <label>Cover frame <span style={{color:"var(--muted)",fontWeight:300}}>(seconds into the video — optional)</span></label>
          <input type="number" min="0" step="0.1" value={coverSec}
            onChange={e=>setCoverSec(e.target.value)}
            placeholder="Blank = first scene image"/>
          <div style={{fontSize:".76rem", color:"var(--muted)", marginTop:".3rem"}}>
            A frame at this time is extracted as the thumbnail. Left blank, the first
            scene's image is used directly.
          </div>
        </div>
      )}

      <div className="toggle-row">
        <input type="checkbox" id="f_fb_sched" checked={schedule}
          onChange={e=>setSchedule(e.target.checked)}/>
        <label htmlFor="f_fb_sched">Schedule release (publish later automatically)</label>
      </div>
      {schedule && (
        <div className="field">
          <label>Release date &amp; time <span style={{color:"var(--muted)",fontWeight:300}}>(your local time)</span></label>
          <input type="datetime-local" value={publishAt}
            onChange={e=>setPublishAt(e.target.value)}/>
          <div style={{fontSize:".76rem", color:"var(--muted)", marginTop:".3rem"}}>
            Facebook publishes it at this time. Must be ≥ 10 minutes out{asReel ? " (Reels: at most 29 days ahead)" : ""}.
          </div>
        </div>
      )}
    </div>
  );
}
