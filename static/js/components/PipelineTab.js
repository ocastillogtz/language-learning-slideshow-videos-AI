// PipelineTab.js
const { useState, useEffect } = React;

const SHOT_TYPES    = ["both", "over_shoulder_A", "over_shoulder_B"];
const PROJECT_TYPES = [
  { value: "shadowing",        label: "Shadowing (with repetitions)"          },
  { value: "story",            label: "Story (no repetitions)"                },
  { value: "word_learning",    label: "Word Learning (vocabulary)"            },
  { value: "register_phrases", label: "Register Phrases (formal / slang / ...)"  },
  { value: "grammar_pairs",   label: "Grammar Pairs (base → transformed)"      },
];

function StepCard({ step, projectName }) {
  const { toast, startPoll, reloadManifest, refreshSidebar } = useApp();
  const [open,    setOpen]    = useState(false);
  const [status,  setStatus]  = useState("idle");
  const [log,     setLog]     = useState("");
  const [running, setRunning] = useState(false);

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
    try {
      const payload = step.payload();
      const d = await apiPost(step.endpoint(projectName), payload);
      const stepKey = d.step_key || step.id;
      startPoll(projectName, stepKey, async (s) => {
        setStatus(s.status);
        setLog(s.log || "");
        setRunning(false);
        if (s.status === "done") {
          toast("Done", `${step.title} completed.`, "ok");
          await reloadManifest(projectName);
          await refreshSidebar();
        } else if (s.status === "error") {
          toast("Error", s.log, "err");
        }
      });
    } catch(e) {
      setStatus("error"); setLog(e.message); setRunning(false);
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
          <div className="run-row">
            <button className="btn-primary" onClick={run} disabled={running}>
              <svg width="11" height="11" viewBox="0 0 11 11" fill="currentColor">
                <polygon points="1,0.5 10.5,5.5 1,10.5"/>
              </svg>
              Run
              {running && <div className="spin" style={{display:"block"}}/>}
            </button>
          </div>
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

  const [projType, setProjType] = useState(meta.project_type_key || gen.project_type_key || "story");
  const [charA,    setCharA]    = useState((gen.characters||[])[0] || "");
  const [charB,    setCharB]    = useState((gen.characters||[])[1] || "");
  const [loc,      setLoc]      = useState(gen.location_key || "");
  const [prompt,   setPrompt]   = useState(gen.prompt_script || "");
  const [loading,  setLoading]  = useState(false);

  // Auto-detect characters from scene description if not already set
  useEffect(() => {
    if ((charA && charB) || !characters.length) return;
    const context = (gen.provided_context || "").toLowerCase();
    if (!context) return;
    const found = characters.filter(c => context.includes(c.toLowerCase()));
    if (found.length >= 1 && !charA) setCharA(found[0]);
    if (found.length >= 2 && !charB) setCharB(found[1]);
  }, [characters]);

  ScriptFields._getPayload = () => ({
    char_a:           charA,
    char_b:           charB,
    location_key:     loc,
    project_type_key: projType,
    prompt_override:  prompt.trim() || null,
  });

  async function loadPrompt() {
    if (!charA || !charB || !loc) {
      toast("Warning", "Select characters and location first.", "err"); return;
    }
    setLoading(true);
    try {
      const d = await apiPost(`/projects/${projectName}/prompt/script`, {
        char_a: charA, char_b: charB, location_key: loc, project_type_key: projType,
      });
      setPrompt(d.prompt);
    } catch(e) { toast("Error", e.message, "err"); }
    finally { setLoading(false); }
  }

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
      <div className="field">
        <label>Location</label>
        <select value={loc} onChange={e=>setLoc(e.target.value)}>
          <option value="">— select —</option>
          {locations.map(l => <option key={l} value={l}>{l}</option>)}
        </select>
      </div>
      <div className="field">
        <label>Project Type</label>
        <select value={projType} onChange={e=>setProjType(e.target.value)}>
          {PROJECT_TYPES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
      </div>
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
  return (
    <div style={{color:"var(--muted)",fontSize:".84rem",padding:".4rem 0"}}>
      No parameters needed — voices are defined in <code>characters.json</code>.
    </div>
  );
}

function ImagesFields() {
  const [overwrite,    setOverwrite]    = useState(false);
  const [ignoreCache,  setIgnoreCache]  = useState(false);
  ImagesFields._getPayload = () => ({ overwrite, ignore_cache: ignoreCache });
  return (
    <div className="fields">
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
    </div>
  );
}

function VideoFields() {
  const [overwrite, setOverwrite] = useState(false);
  const [annotated, setAnnotated] = useState(false);
  VideoFields._getPayload = () => ({ overwrite, annotated_subtitles: annotated });
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
    </div>
  );
}

function AssembleFields() {
  const [bgAudio,       setBgAudio]       = useState("office");
  const [speedFactor,   setSpeedFactor]   = useState("1.0");
  const [overwrite,     setOverwrite]     = useState(false);
  const [brandingFile,  setBrandingFile]  = useState("");
  const [brandingMode,  setBrandingMode]  = useState("none");
  const [brandingFiles, setBrandingFiles] = useState([]);

  AssembleFields._getPayload = () => ({
    bg_audio_name: bgAudio,
    overwrite,
    speed_factor:  speedFactor !== "" ? parseFloat(speedFactor) : null,
    branding_file: brandingMode !== "none" ? brandingFile : null,
    branding_mode: brandingMode,
  });

  useEffect(() => {
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

  return (
    <div className="fields">
      <div className="field-row">
        <div className="field" style={{flex:2}}>
          <label>Background Audio</label>
          <input value={bgAudio} onChange={e=>setBgAudio(e.target.value)}
            placeholder="e.g. office, elevator"/>
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

function UploadFields() {
  const [privacy,    setPrivacy]    = useState("private");
  const [title,      setTitle]      = useState("");
  const [desc,       setDesc]       = useState("");
  const [resetMsg,   setResetMsg]   = useState("");
  const [resetting,  setResetting]  = useState(false);

  UploadFields._getPayload = () => ({ privacy, title, description: desc });

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
        <label>Privacy</label>
        <select value={privacy} onChange={e=>setPrivacy(e.target.value)}>
          <option value="private">Private</option>
          <option value="unlisted">Unlisted</option>
          <option value="public">Public</option>
        </select>
      </div>
      <div className="field">
        <label>Title Override <span style={{color:"var(--muted)",fontWeight:300}}>(optional)</span></label>
        <input value={title} onChange={e=>setTitle(e.target.value)}
          placeholder="Leave blank to use manifest title"/>
      </div>
      <div className="field">
        <label>Description Override <span style={{color:"var(--muted)",fontWeight:300}}>(optional)</span></label>
        <textarea rows={3} value={desc} onChange={e=>setDesc(e.target.value)}
          placeholder="Leave blank to auto-generate"/>
      </div>
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

// ── Step definitions ───────────────────────────────────────────────────────────

function makeSteps(projectName) {
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
      id:"audio", num:2,
      title:"Generate Audio",
      desc:"ElevenLabs TTS for narration, dialogue, and repetitions.",
      Fields: AudioFields,
      payload: () => ({}),
      endpoint: n => `/projects/${n}/run/audio`,
    },
    {
      id:"images", num:3,
      title:"Generate Images",
      desc:"fal.ai generates scene images for every dialogue line.",
      Fields: ImagesFields,
      payload: () => ImagesFields._getPayload?.() || {},
      endpoint: n => `/projects/${n}/run/images`,
    },
    {
      id:"video", num:4,
      title:"Render Scene Clips",
      desc:"MoviePy renders one .mp4 per scene.",
      Fields: VideoFields,
      payload: () => VideoFields._getPayload?.() || {},
      endpoint: n => `/projects/${n}/run/video`,
    },
    {
      id:"assemble", num:5,
      title:"Assemble Final Video",
      desc:"Concatenates clips, adds background music and branding.",
      Fields: AssembleFields,
      payload: () => AssembleFields._getPayload?.() || {},
      endpoint: n => `/projects/${n}/run/assemble`,
    },
    {
      id:"upload", num:6,
      title:"Upload to YouTube",
      desc:"Metadata auto-read from manifest.",
      Fields: UploadFields,
      payload: () => UploadFields._getPayload?.() || {},
      endpoint: n => `/projects/${n}/run/upload`,
    },
    {
      id:"upload_instagram", num:7,
      title:"Upload to Instagram",
      desc:"Publish as a Reel via Instagram Graph API.",
      Fields: InstagramUploadFields,
      payload: () => InstagramUploadFields._getPayload?.() || {},
      endpoint: n => `/projects/${n}/run/upload_instagram`,
    },
  ];
}

function PipelineTab({ projectName }) {
  const steps = makeSteps(projectName);
  return (
    <div className="pipeline">
      {steps.map(step => (
        <StepCard key={step.id} step={step} projectName={projectName}/>
      ))}
    </div>
  );
}

// ── Instagram Upload Fields ───────────────────────────────────────────────────

function InstagramUploadFields() {
  const [caption,      setCaption]      = React.useState("");
  const [shareToFeed,  setShareToFeed]  = React.useState(true);

  // Setup section state
  const [appId,        setAppId]        = React.useState("");
  const [appSecret,    setAppSecret]    = React.useState("");
  const [shortToken,   setShortToken]   = React.useState("");
  const [igUserId,     setIgUserId]     = React.useState("");
  const [setupMsg,     setSetupMsg]     = React.useState("");
  const [settingUp,    setSettingUp]    = React.useState(false);

  // Status section state
  const [status,       setStatus]       = React.useState(null);
  const [resetting,    setResetting]    = React.useState(false);
  const [resetMsg,     setResetMsg]     = React.useState("");

  InstagramUploadFields._getPayload = () => ({ caption, share_to_feed: shareToFeed });

  React.useEffect(() => {
    fetch("/auth/instagram/status")
      .then(r => r.json())
      .then(d => setStatus(d))
      .catch(() => {});
  }, []);

  async function doSetup() {
    setSettingUp(true); setSetupMsg("");
    try {
      const r = await fetch("/auth/instagram/setup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ app_id: appId, app_secret: appSecret, short_token: shortToken, ig_user_id: igUserId }),
      });
      const d = await r.json();
      setSetupMsg(d.message || d.error || "Done");
      if (d.message) {
        const s = await fetch("/auth/instagram/status").then(x => x.json());
        setStatus(s);
      }
    } catch(e) { setSetupMsg("Request failed: " + e.message); }
    finally { setSettingUp(false); }
  }

  async function doReset() {
    setResetting(true); setResetMsg("");
    try {
      const r = await fetch("/auth/instagram/reset", { method: "POST" });
      const d = await r.json();
      setResetMsg(d.message || d.error || "Done");
      if (d.message) setStatus({ configured: false, days_left: 0 });
    } catch(e) { setResetMsg("Request failed: " + e.message); }
    finally { setResetting(false); }
  }

  const tokenOk = status && status.configured;

  return (
    <div className="fields">
      {/* Token status banner */}
      {status && (
        <div style={{
          padding: ".5rem .75rem",
          borderRadius: "6px",
          marginBottom: ".75rem",
          fontSize: ".8rem",
          background: tokenOk ? "rgba(74,222,128,.12)" : "rgba(248,113,113,.12)",
          color: tokenOk ? "var(--green, #4ade80)" : "var(--red, #f87171)",
          border: `1px solid ${tokenOk ? "rgba(74,222,128,.3)" : "rgba(248,113,113,.3)"}`,
        }}>
          {tokenOk
            ? `Connected — token valid for ${status.days_left} more day${status.days_left !== 1 ? "s" : ""}`
            : "Not configured — fill in the Setup section below"}
        </div>
      )}

      {/* Upload options */}
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

      {/* Setup section */}
      <div style={{borderTop:"1px solid var(--border)", paddingTop:".75rem", marginTop:".5rem"}}>
        <div style={{fontSize:".85rem", fontWeight:600, marginBottom:".5rem", color:"var(--fg)"}}>
          {tokenOk ? "Re-authenticate" : "Setup (one-time)"}
        </div>
        <div style={{fontSize:".78rem", color:"var(--muted)", marginBottom:".6rem"}}>
          Get a short-lived token from the{" "}
          <a href="https://developers.facebook.com/tools/explorer/" target="_blank"
             rel="noreferrer" style={{color:"var(--accent)"}}>
            Graph API Explorer
          </a>{" "}
          with <code>instagram_basic</code>, <code>instagram_content_publish</code> permissions.
        </div>
        <div className="field-row">
          <div className="field">
            <label>App ID</label>
            <input value={appId} onChange={e=>setAppId(e.target.value)} placeholder="1234567890"/>
          </div>
          <div className="field">
            <label>App Secret</label>
            <input type="password" value={appSecret} onChange={e=>setAppSecret(e.target.value)} placeholder="abc123..."/>
          </div>
        </div>
        <div className="field">
          <label>Short-Lived Token</label>
          <input value={shortToken} onChange={e=>setShortToken(e.target.value)}
            placeholder="EAA..."/>
        </div>
        <div className="field">
          <label>
            Instagram User ID{" "}
            <span style={{color:"var(--muted)",fontWeight:300}}>(optional — auto-detected if blank)</span>
          </label>
          <input value={igUserId} onChange={e=>setIgUserId(e.target.value)}
            placeholder="e.g. 17841400000000000"/>
          <div style={{fontSize:".74rem",color:"var(--muted)",marginTop:".3rem"}}>
            Find it in Graph API Explorer:{" "}
            <code style={{fontSize:".74rem"}}>GET /me/accounts?fields=instagram_business_account</code>
            {" "}or query your Page username directly.
          </div>
        </div>
        <button className="btn-primary" onClick={doSetup} disabled={settingUp || !appId || !appSecret || !shortToken}
          style={{fontSize:".8rem", marginTop:".25rem"}}>
          {settingUp ? "Saving…" : "Save Credentials"}
        </button>
        {setupMsg && (
          <div style={{marginTop:".4rem", fontSize:".78rem", color:"var(--muted)"}}>{setupMsg}</div>
        )}
      </div>

      {/* Reset section */}
      {tokenOk && (
        <div style={{borderTop:"1px solid var(--border)", paddingTop:".75rem", marginTop:".5rem"}}>
          <div style={{fontSize:".78rem", color:"var(--muted)", marginBottom:".5rem"}}>
            Token expired or revoked? Clear it here — the next upload will fail until you re-authenticate above.
          </div>
          <button className="btn-cancel" onClick={doReset} disabled={resetting} style={{fontSize:".8rem"}}>
            {resetting ? "Clearing…" : "Reset Instagram Login"}
          </button>
          {resetMsg && (
            <div style={{marginTop:".4rem", fontSize:".78rem", color:"var(--muted)"}}>{resetMsg}</div>
          )}
        </div>
      )}
    </div>
  );
}
