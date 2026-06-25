// AssetsTab.js — global asset management panel
// Tabs: Characters · Locations · Project Types · Background Audio · SFX
const { useState, useEffect, useCallback } = React;

// ── Shared helpers ────────────────────────────────────────────────────────────

function Section({ title, children }) {
  return (
    <div style={{marginBottom:"2rem"}}>
      <div style={{
        fontSize:".7rem",fontWeight:600,letterSpacing:".08em",
        textTransform:"uppercase",color:"var(--muted)",marginBottom:".75rem"
      }}>{title}</div>
      {children}
    </div>
  );
}

function AssetRow({ label, meta, onEdit, onRemove, onAction, actionLabel }) {
  return (
    <div style={{
      display:"flex",alignItems:"center",gap:".6rem",
      padding:".55rem .75rem",borderRadius:6,
      background:"var(--surface)",border:"1px solid var(--border)",
      marginBottom:".4rem",
    }}>
      <div style={{flex:1,minWidth:0}}>
        <div style={{fontWeight:500,fontSize:".88rem"}}>{label}</div>
        {meta && <div style={{fontSize:".76rem",color:"var(--muted)",marginTop:".15rem",
          overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{meta}</div>}
      </div>
      {onAction && actionLabel && (
        <button className="btn-ghost" style={{fontSize:".74rem",padding:".25rem .6rem"}}
          onClick={onAction}>{actionLabel}</button>
      )}
      {onEdit && (
        <button className="btn-ghost" style={{fontSize:".74rem",padding:".25rem .6rem"}}
          onClick={onEdit}>Edit</button>
      )}
      {onRemove && (
        <button className="btn-ghost" style={{fontSize:".74rem",padding:".25rem .6rem",color:"var(--err,#e55)"}}
          onClick={onRemove}>Remove</button>
      )}
    </div>
  );
}

function FieldRow({ label, children }) {
  return (
    <div className="field" style={{marginBottom:".6rem"}}>
      <label>{label}</label>
      {children}
    </div>
  );
}

function FormPanel({ title, onSave, onCancel, saving, children }) {
  return (
    <div style={{
      border:"1px solid var(--border)",borderRadius:8,padding:"1rem",
      marginBottom:"1rem",background:"var(--surface)"
    }}>
      <div style={{fontWeight:600,marginBottom:".75rem"}}>{title}</div>
      {children}
      <div style={{display:"flex",gap:".5rem",marginTop:".75rem"}}>
        <button className="btn-primary" onClick={onSave} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button className="btn-cancel" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

// ── Reference image upload helper ────────────────────────────────────────────

function RefImagePicker({ name, existingPath, onUploaded }) {
  // Used both inline (during add, before the character exists) and standalone
  // (for an already-saved character).
  const { toast }                     = useApp();
  const [file,      setFile]          = useState(null);
  const [preview,   setPreview]       = useState(null);
  const [uploading, setUploading]     = useState(false);
  const inputRef = React.useRef(null);

  function pickFile(e) {
    const f = e.target.files[0];
    if (!f) return;
    setFile(f);
    const reader = new FileReader();
    reader.onload = ev => setPreview(ev.target.result);
    reader.readAsDataURL(f);
  }

  async function upload() {
    if (!file || !name) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const d = await apiPostForm(`/assets/characters/${name}/upload-reference`, fd);
      toast("Saved", "Reference drawing uploaded.", "ok");
      setFile(null); setPreview(null);
      if (onUploaded) onUploaded(d.file_path);
    } catch(e) { toast("Error", e.message, "err"); }
    finally { setUploading(false); }
  }

  const currentImg = preview
    ? preview
    : existingPath ? `/asset-files/${existingPath}` : null;

  return (
    <div style={{display:"flex",gap:"1rem",alignItems:"flex-start",flexWrap:"wrap"}}>
      {currentImg && (
        <img src={currentImg} alt="reference"
          style={{width:96,height:96,objectFit:"cover",borderRadius:6,
            border:"1px solid var(--border)",flexShrink:0}}/>
      )}
      <div style={{flex:1,minWidth:160}}>
        <div style={{fontSize:".78rem",color:"var(--muted)",marginBottom:".35rem"}}>
          {existingPath && !preview ? "Current reference drawing" : "Upload a reference drawing (PNG, JPG, WEBP)"}
        </div>
        <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp"
          style={{display:"none"}} onChange={pickFile}/>
        <div style={{display:"flex",gap:".4rem",alignItems:"center",flexWrap:"wrap"}}>
          <button className="btn-ghost" style={{fontSize:".78rem",padding:".3rem .6rem"}}
            onClick={() => inputRef.current.click()}>
            {existingPath && !preview ? "Change Drawing" : "Choose File"}
          </button>
          {file && (
            <>
              <span style={{fontSize:".75rem",color:"var(--muted)",maxWidth:160,
                overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{file.name}</span>
              {name && (
                <button className="btn-primary" style={{fontSize:".78rem",padding:".3rem .65rem"}}
                  onClick={upload} disabled={uploading}>
                  {uploading ? "Uploading…" : "Upload"}
                </button>
              )}
            </>
          )}
        </div>
        {file && !name && (
          <div style={{fontSize:".73rem",color:"var(--muted)",marginTop:".3rem"}}>
            Save the character first — then upload the drawing.
          </div>
        )}
      </div>
    </div>
  );
}

// ── Characters ────────────────────────────────────────────────────────────────

function CharactersPane() {
  const { toast, loadAssets } = useApp();
  const [data,    setData]    = useState({});
  const [adding,  setAdding]  = useState(false);
  const [editing, setEditing] = useState(null); // key being edited
  const [saving,  setSaving]  = useState(false);
  const [genKey,  setGenKey]  = useState(null);
  const [form,    setForm]    = useState({
    name:"", voice_id:"", fixed_description:"",
    variable_description:"", height_cm:"", ref_desc:""
  });
  // Pending file for upload right after character creation
  const pendingFileRef = React.useRef(null);

  const load = useCallback(async () => {
    try { setData(await apiGet("/assets/characters")); } catch {}
  }, []);

  useEffect(() => { load(); }, []);

  function startAdd() {
    setForm({ name:"", voice_id:"", fixed_description:"", variable_description:"", height_cm:"", ref_desc:"" });
    pendingFileRef.current = null;
    setEditing(null); setAdding(true);
  }
  function startEdit(key) {
    const c = data[key] || {};
    setForm({
      name: key,
      voice_id: c.voice_id || "",
      fixed_description: c.fixed_description || "",
      variable_description: c.variable_description || "",
      height_cm: c.height_cm ? String(c.height_cm) : "",
      ref_desc: c.ref_desc || "",
    });
    setAdding(false); setEditing(key);
  }

  async function saveAdd() {
    if (!form.name || !form.voice_id || !form.fixed_description || !form.variable_description) {
      toast("Error","Name, Voice ID, Fixed Description and Variable Description are required.","err"); return;
    }
    setSaving(true);
    try {
      await apiPost("/assets/characters", {
        ...form,
        height_cm: form.height_cm ? Number(form.height_cm) : null
      });
      // Upload pending reference drawing if the user selected one
      if (pendingFileRef.current) {
        try {
          const fd = new FormData();
          fd.append("file", pendingFileRef.current);
          await apiPostForm(`/assets/characters/${form.name}/upload-reference`, fd);
        } catch(e) {
          toast("Warning", `Character saved but drawing upload failed: ${e.message}`, "err");
        }
      }
      toast("Saved", `Character "${form.name}" added.`, "ok");
      setAdding(false); pendingFileRef.current = null;
      await load(); await loadAssets();
    } catch(e) { toast("Error", e.message, "err"); }
    finally { setSaving(false); }
  }

  async function saveEdit() {
    setSaving(true);
    try {
      await apiPut(`/assets/characters/${editing}`, {
        ...form,
        height_cm: form.height_cm ? Number(form.height_cm) : null
      });
      toast("Saved", `Character "${editing}" updated.`, "ok");
      setEditing(null); await load(); await loadAssets();
    } catch(e) { toast("Error", e.message, "err"); }
    finally { setSaving(false); }
  }

  async function remove(key) {
    if (!confirm(`Remove character "${key}"?`)) return;
    try {
      await apiDelete(`/assets/characters/${key}`);
      toast("Removed", `"${key}" removed.`, "ok"); await load(); await loadAssets();
    } catch(e) { toast("Error", e.message, "err"); }
  }

  async function genArt(key) {
    const hasRef = !!data[key]?.ref_drawing_file_path;
    const msg = hasRef
      ? `Generate artwork for "${key}" using the reference drawing? This will call fal.ai.`
      : `Generate artwork for "${key}" via fal.ai? No reference drawing — will use text description only.`;
    if (!confirm(msg)) return;
    setGenKey(key);
    try {
      await apiPost(`/assets/characters/${key}/generate-art`, {});
      toast("Started", `Art generation queued for "${key}".`, "ok");
    } catch(e) { toast("Error", e.message, "err"); }
    finally { setGenKey(null); }
  }

  const f  = (k) => <input value={form[k]} onChange={e=>setForm(p=>({...p,[k]:e.target.value}))}/>;
  const fa = (k, r) => <textarea rows={r||2} value={form[k]} onChange={e=>setForm(p=>({...p,[k]:e.target.value}))}/>;

  // Inline file picker that stores the file in pendingFileRef without uploading yet
  function InlineFilePicker() {
    const [preview, setPreview] = useState(null);
    const [fname,   setFname]   = useState("");
    const inputRef = React.useRef(null);
    function pick(e) {
      const f = e.target.files[0];
      if (!f) return;
      pendingFileRef.current = f;
      setFname(f.name);
      const reader = new FileReader();
      reader.onload = ev => setPreview(ev.target.result);
      reader.readAsDataURL(f);
    }
    return (
      <div style={{display:"flex",gap:"1rem",alignItems:"flex-start"}}>
        {preview && (
          <img src={preview} alt="preview"
            style={{width:80,height:80,objectFit:"cover",borderRadius:6,
              border:"1px solid var(--border)",flexShrink:0}}/>
        )}
        <div>
          <div style={{fontSize:".78rem",color:"var(--muted)",marginBottom:".35rem"}}>
            Optional reference drawing — uploaded together with the character.
          </div>
          <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp"
            style={{display:"none"}} onChange={pick}/>
          <div style={{display:"flex",gap:".4rem",alignItems:"center"}}>
            <button type="button" className="btn-ghost"
              style={{fontSize:".78rem",padding:".3rem .6rem"}}
              onClick={()=>inputRef.current.click()}>Choose Drawing</button>
            {fname && <span style={{fontSize:".75rem",color:"var(--muted)"}}>{fname}</span>}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div>
      {(adding || editing) && (
        <FormPanel
          title={adding ? "Add Character" : `Edit: ${editing}`}
          onSave={adding ? saveAdd : saveEdit}
          onCancel={() => { setAdding(false); setEditing(null); }}
          saving={saving}
        >
          {adding && <FieldRow label="Name">{f("name")}</FieldRow>}
          <FieldRow label="ElevenLabs Voice ID">{f("voice_id")}</FieldRow>
          <FieldRow label="Fixed Description (ethnicity, face, build — never changes)">{fa("fixed_description", 2)}</FieldRow>
          <FieldRow label="Variable Description (clothing, hair — GPT may adjust)">{fa("variable_description", 2)}</FieldRow>
          <FieldRow label="Height (cm, optional)">{f("height_cm")}</FieldRow>
          <FieldRow label="Ref Description (optional, for image prompts)">{fa("ref_desc", 2)}</FieldRow>
          {adding && (
            <FieldRow label="Reference Drawing (optional — used to guide art generation)">
              <InlineFilePicker/>
            </FieldRow>
          )}
        </FormPanel>
      )}

      {!adding && (
        <button className="btn-primary" style={{marginBottom:"1rem",fontSize:".83rem"}}
          onClick={startAdd}>+ Add Character</button>
      )}

      {Object.keys(data).length === 0 && (
        <div style={{color:"var(--muted)",fontSize:".83rem"}}>No characters yet.</div>
      )}
      {Object.entries(data).map(([key, c]) => (
        <div key={key} style={{marginBottom:".75rem"}}>
          <AssetRow
            label={key}
            meta={c.fixed_description}
            onEdit={() => startEdit(key)}
            onRemove={() => remove(key)}
            onAction={() => genArt(key)}
            actionLabel={genKey===key ? "Generating…" : "🎨 Gen Art"}
          />
          {/* Reference drawing row — shown below the character card */}
          {editing !== key && (
            <div style={{
              padding:".6rem .75rem .75rem",
              borderLeft:"1px solid var(--border)",
              borderRight:"1px solid var(--border)",
              borderBottom:"1px solid var(--border)",
              borderRadius:"0 0 6px 6px",
              background:"var(--bg)",
              marginTop:"-4px",
            }}>
              <div style={{fontSize:".72rem",fontWeight:600,color:"var(--muted)",
                letterSpacing:".06em",textTransform:"uppercase",marginBottom:".45rem"}}>
                Reference Drawing
              </div>
              <RefImagePicker
                name={key}
                existingPath={c.ref_drawing_file_path}
                onUploaded={() => load()}
              />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Locations ─────────────────────────────────────────────────────────────────

function LocationsPane() {
  const { toast } = useApp();
  const [data,    setData]    = useState({});
  const [adding,  setAdding]  = useState(false);
  const [editing, setEditing] = useState(null);
  const [saving,  setSaving]  = useState(false);
  const [genKey,  setGenKey]  = useState(null);
  const [form,    setForm]    = useState({ key:"", description:"", creation_prompt:"" });

  const load = useCallback(async () => {
    try { setData(await apiGet("/assets/locations")); } catch {}
  }, []);
  useEffect(() => { load(); }, []);

  function startAdd() { setForm({ key:"", description:"", creation_prompt:"" }); setEditing(null); setAdding(true); }
  function startEdit(key) {
    const l = data[key] || {};
    setForm({ key, description: l.description||"", creation_prompt: l.creation_prompt||"" });
    setAdding(false); setEditing(key);
  }

  async function saveAdd() {
    if (!form.key || !form.description || !form.creation_prompt) {
      toast("Error","Key, description and creation prompt required.","err"); return;
    }
    setSaving(true);
    try {
      await apiPost("/assets/locations", form);
      toast("Saved", `Location "${form.key}" added.`, "ok"); setAdding(false); await load();
    } catch(e) { toast("Error", e.message, "err"); }
    finally { setSaving(false); }
  }

  async function saveEdit() {
    setSaving(true);
    try {
      await apiPut(`/assets/locations/${editing}`, { description: form.description, creation_prompt: form.creation_prompt });
      toast("Saved", `Location "${editing}" updated.`, "ok"); setEditing(null); await load();
    } catch(e) { toast("Error", e.message, "err"); }
    finally { setSaving(false); }
  }

  async function remove(key) {
    if (!confirm(`Remove location "${key}"?`)) return;
    try { await apiDelete(`/assets/locations/${key}`); toast("Removed","","ok"); await load(); }
    catch(e) { toast("Error", e.message, "err"); }
  }

  async function genArt(key) {
    if (!confirm(`Generate background art for "${key}" via fal.ai?`)) return;
    setGenKey(key);
    try {
      await apiPost(`/assets/locations/${key}/generate-art`, {});
      // Poll until the background job finishes, then reload data
      const stepKey = `loc_art_${key}`;
      while (true) {
        await new Promise(r => setTimeout(r, 2000));
        const s = await fetch(`/projects/assets/status/${stepKey}`).then(r => r.json());
        if (s.status === "done")  { toast("Done", `Art generated for "${key}".`, "ok"); break; }
        if (s.status === "error") { toast("Error", s.log || "Art generation failed.", "err"); break; }
      }
      await load();
    } catch(e) { toast("Error", e.message, "err"); }
    finally { setGenKey(null); }
  }

  const f  = (k) => <input value={form[k]} onChange={e=>setForm(p=>({...p,[k]:e.target.value}))}/>;
  const fa = (k, r) => <textarea rows={r||2} value={form[k]} onChange={e=>setForm(p=>({...p,[k]:e.target.value}))}/>;

  return (
    <div>
      {(adding || editing) && (
        <FormPanel title={adding?"Add Location":`Edit: ${editing}`}
          onSave={adding?saveAdd:saveEdit} onCancel={()=>{setAdding(false);setEditing(null);}} saving={saving}>
          {adding && <FieldRow label="Key (lowercase, underscores)">{f("key")}</FieldRow>}
          <FieldRow label="Description">{fa("description", 2)}</FieldRow>
          <FieldRow label="Creation Prompt (for fal.ai image generation)">{fa("creation_prompt", 3)}</FieldRow>
        </FormPanel>
      )}

      {!adding && (
        <button className="btn-primary" style={{marginBottom:"1rem",fontSize:".83rem"}}
          onClick={startAdd}>+ Add Location</button>
      )}

      {Object.keys(data).length === 0 && (
        <div style={{color:"var(--muted)",fontSize:".83rem"}}>No locations yet.</div>
      )}
      {Object.entries(data).map(([key, l]) => (
        <div key={key} style={{
          background:"var(--surface)",border:"1px solid var(--border)",
          borderRadius:6,marginBottom:".4rem",overflow:"hidden",
        }}>
          <div style={{display:"flex",alignItems:"center",gap:".6rem",padding:".55rem .75rem"}}>
            {l.artwork_file_path && (
              <img src={`/asset-files/${l.artwork_file_path}`}
                style={{width:48,height:64,objectFit:"cover",borderRadius:4,flexShrink:0}}
                alt={key}/>
            )}
            <div style={{flex:1,minWidth:0}}>
              <div style={{fontWeight:500,fontSize:".88rem"}}>{key}</div>
              <div style={{fontSize:".76rem",color:"var(--muted)",marginTop:".15rem",
                overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{l.description}</div>
            </div>
            <button className="btn-ghost" style={{fontSize:".74rem",padding:".25rem .6rem"}}
              onClick={()=>genArt(key)} disabled={genKey===key}>
              {genKey===key ? "Generating…" : "🎨 Gen Art"}
            </button>
            <button className="btn-ghost" style={{fontSize:".74rem",padding:".25rem .6rem"}}
              onClick={()=>startEdit(key)}>Edit</button>
            <button className="btn-ghost" style={{fontSize:".74rem",padding:".25rem .6rem",color:"var(--err,#e55)"}}
              onClick={()=>remove(key)}>Remove</button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Project Types ─────────────────────────────────────────────────────────────

function ProjectTypesPane() {
  const { toast } = useApp();
  const [data, setData] = useState({});
  const [open, setOpen] = useState(null);

  const load = useCallback(async () => {
    try { setData(await apiGet("/assets/project-types")); } catch {}
  }, []);
  useEffect(() => { load(); }, []);

  return (
    <div>
      <div style={{fontSize:".82rem",color:"var(--muted)",marginBottom:".75rem"}}>
        Project types are defined in <code>assets/project_types/project_types.json</code>.
        Edit the file directly to modify prompts and scene builder rules.
      </div>
      {Object.keys(data).length === 0 && (
        <div style={{color:"var(--muted)",fontSize:".83rem"}}>No project types found.</div>
      )}
      {Object.entries(data).map(([key, pt]) => (
        <div key={key} style={{
          border:"1px solid var(--border)",borderRadius:6,marginBottom:".5rem",
          background:"var(--surface)"
        }}>
          <div style={{padding:".55rem .75rem",display:"flex",alignItems:"center",gap:".5rem",cursor:"pointer"}}
            onClick={()=>setOpen(o=>o===key?null:key)}>
            <div style={{flex:1,fontWeight:500,fontSize:".88rem"}}>{key}</div>
            <div style={{fontSize:".75rem",color:"var(--muted)"}}>{pt.self_description || ""}</div>
            <div style={{fontSize:".8rem",color:"var(--muted)"}}>{open===key?"▲":"▼"}</div>
          </div>
          {open===key && (
            <div style={{padding:".5rem .75rem 1rem",borderTop:"1px solid var(--border)"}}>
              <div style={{fontSize:".78rem",color:"var(--muted)",marginBottom:".4rem"}}>Scene Builder Rules</div>
              <pre style={{fontSize:".74rem",background:"var(--bg)",padding:".5rem",borderRadius:4,overflow:"auto"}}>
                {JSON.stringify(pt.scene_builder_rules || {}, null, 2)}
              </pre>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Background Audio ──────────────────────────────────────────────────────────

function BackgroundAudioPane() {
  const { toast } = useApp();
  const [data, setData] = useState({});

  const load = useCallback(async () => {
    try { setData(await apiGet("/assets/background-audio")); } catch {}
  }, []);
  useEffect(() => { load(); }, []);

  async function remove(key) {
    if (!confirm(`Remove background audio "${key}"?`)) return;
    try { await apiDelete(`/assets/background-audio/${key}`); toast("Removed","","ok"); await load(); }
    catch(e) { toast("Error", e.message, "err"); }
  }

  return (
    <div>
      <div style={{fontSize:".82rem",color:"var(--muted)",marginBottom:".75rem"}}>
        Audio files live in <code>assets/background_audio/</code>. Register them here to use in assembly.
      </div>
      {Object.keys(data).length === 0 && (
        <div style={{color:"var(--muted)",fontSize:".83rem"}}>No background audio registered.</div>
      )}
      {Object.entries(data).map(([key, a]) => (
        <AssetRow key={key} label={key} meta={a.file_path || a.description || ""}
          onRemove={()=>remove(key)}/>
      ))}
    </div>
  );
}

// ── SFX ───────────────────────────────────────────────────────────────────────

function SfxPane() {
  const { toast } = useApp();
  const [data, setData] = useState({});

  const load = useCallback(async () => {
    try { setData(await apiGet("/assets/sfx")); } catch {}
  }, []);
  useEffect(() => { load(); }, []);

  async function remove(key) {
    if (!confirm(`Remove SFX "${key}"?`)) return;
    try { await apiDelete(`/assets/sfx/${key}`); toast("Removed","","ok"); await load(); }
    catch(e) { toast("Error", e.message, "err"); }
  }

  return (
    <div>
      <div style={{fontSize:".82rem",color:"var(--muted)",marginBottom:".75rem"}}>
        SFX files live in <code>assets/sfx/</code>.
      </div>
      {Object.keys(data).length === 0 && (
        <div style={{color:"var(--muted)",fontSize:".83rem"}}>No SFX registered.</div>
      )}
      {Object.entries(data).map(([key, s]) => (
        <AssetRow key={key} label={key} meta={s.file_path || s.description || ""}
          onRemove={()=>remove(key)}/>
      ))}
    </div>
  );
}

// ── PUT helper (not in api.js yet) ────────────────────────────────────────────

async function apiPut(path, body) {
  const r = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || r.statusText);
  return d;
}

// ── Subtitle / narration preview ──────────────────────────────────────────────

function SubtitlePreviewPane() {
  const [format,   setFormat]   = useState("vertical");
  const [style,    setStyle]    = useState("dialog");
  const [text,     setText]     = useState("Guten Morgen! Wie geht es dir heute?");
  const [footnote, setFootnote] = useState("");
  const [repeat,   setRepeat]   = useState("");
  const [src,      setSrc]      = useState("");
  const [loading,  setLoading]  = useState(false);
  const [err,      setErr]      = useState("");

  async function generate() {
    setErr(""); setLoading(true);
    try {
      const p = new URLSearchParams({ text, format, style, footnote, repeat_message: repeat });
      const r = await fetch(`/preview/text?${p.toString()}`);
      if (!r.ok) {
        let msg = r.statusText;
        try { msg = (await r.json()).error || msg; } catch {}
        throw new Error(msg);
      }
      const blob = await r.blob();
      setSrc(prev => { if (prev) URL.revokeObjectURL(prev); return URL.createObjectURL(blob); });
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  }

  return (
    <div>
      <div style={{fontSize:".83rem", color:"var(--muted)", marginBottom:"1rem"}}>
        Preview how narration / subtitle text looks over a sample background
        (<code>assets/samples/{format}.png</code>), using the live config styling for
        that orientation. Matches the real render.
      </div>

      <div className="field-row">
        <div className="field">
          <label>Orientation</label>
          <select value={format} onChange={e=>setFormat(e.target.value)}>
            <option value="vertical">Vertical (1080×1920)</option>
            <option value="horizontal">Horizontal (1920×1080)</option>
          </select>
        </div>
        <div className="field">
          <label>Text style</label>
          <select value={style} onChange={e=>setStyle(e.target.value)}>
            <option value="dialog">Dialogue subtitle (bottom)</option>
            <option value="narration">Narration / title (centered)</option>
          </select>
        </div>
      </div>

      <div className="field">
        <label>Text</label>
        <textarea rows={2} value={text} onChange={e=>setText(e.target.value)}
          placeholder="Type the line to preview…"/>
      </div>
      <div className="field">
        <label>Footnote / disclaimer <span style={{color:"var(--muted)",fontWeight:300}}>(optional)</span></label>
        <textarea rows={2} value={footnote} onChange={e=>setFootnote(e.target.value)}
          placeholder="e.g. * AI-generated content."/>
      </div>
      <div className="field">
        <label>Centered “repeat” message <span style={{color:"var(--muted)",fontWeight:300}}>(optional — shadowing overlay)</span></label>
        <input value={repeat} onChange={e=>setRepeat(e.target.value)} placeholder="e.g. Jetzt wiederholen"/>
      </div>

      <button className="btn-primary" onClick={generate} disabled={loading}
        style={{marginTop:".25rem"}}>
        {loading ? "Rendering…" : "Generate preview"}
      </button>

      {err && (
        <div className="step-log vis err" style={{marginTop:".75rem"}}>{err}</div>
      )}

      {src && !err && (
        <div style={{marginTop:"1rem", textAlign:"center"}}>
          <img src={src} alt="preview"
            style={{maxWidth:"100%", maxHeight:"560px", borderRadius:"8px",
              border:"1px solid var(--border)", background:"#000"}}/>
        </div>
      )}
    </div>
  );
}

// ── Top-level tab panel ───────────────────────────────────────────────────────

const ASSET_TABS = [
  { id:"characters",  label:"Characters"      },
  { id:"locations",   label:"Locations"       },
  { id:"proj_types",  label:"Project Types"   },
  { id:"bg_audio",    label:"Background Audio"},
  { id:"sfx",         label:"SFX"             },
  { id:"preview",     label:"Subtitle Preview"},
];

function AssetsTab() {
  const [tab, setTab] = useState("characters");

  return (
    <div style={{maxWidth:720,margin:"0 auto",padding:"1.5rem 1rem"}}>
      <div style={{marginBottom:"1.5rem"}}>
        <h2 style={{marginBottom:".25rem"}}>Asset Library</h2>
        <div style={{fontSize:".83rem",color:"var(--muted)"}}>
          Manage characters, locations, and other reusable assets.
        </div>
      </div>

      <div className="tabs" style={{marginBottom:"1.25rem"}}>
        {ASSET_TABS.map(t => (
          <button key={t.id}
            className={"tab" + (tab===t.id?" active":"")}
            onClick={()=>setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab==="characters"  && <CharactersPane/>}
      {tab==="locations"   && <LocationsPane/>}
      {tab==="proj_types"  && <ProjectTypesPane/>}
      {tab==="bg_audio"    && <BackgroundAudioPane/>}
      {tab==="sfx"         && <SfxPane/>}
      {tab==="preview"     && <SubtitlePreviewPane/>}
    </div>
  );
}
