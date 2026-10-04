// AssetsTab.js — the Assets view: everything videos are built from.
//
//   Characters · Locations   per workspace (art lives in assets/characters, assets/locations)
//   Music · SFX              shared library used by every workspace (library/music, library/sfx)
//   Branding                 intro/outro clips + branding images of the workspace
//
// Cards show the artwork / play the media inline; clicking one opens a side drawer
// to edit it. "Used by" counts come from the project index (GET /assets/usage).
const { useState, useEffect, useCallback, useRef, useMemo, createContext, useContext } = React;

// ── One shared audio player (only one track plays at a time) ──────────────────

const AsAudioCtx = createContext(null);

function AsAudioProvider({ children }) {
  const audioRef = useRef(null);
  const [cur, setCur]   = useState(null);           // id of the playing item
  const [prog, setProg] = useState({ t: 0, d: 0 });

  useEffect(() => {
    const a = new Audio();
    a.preload = "none";
    a.addEventListener("timeupdate", () => setProg({ t: a.currentTime, d: a.duration || 0 }));
    a.addEventListener("ended", () => setCur(null));
    audioRef.current = a;
    return () => { a.pause(); a.src = ""; };
  }, []);

  const toggle = useCallback((id, src) => {
    const a = audioRef.current;
    if (cur === id) { a.pause(); setCur(null); return; }
    a.src = src;
    a.currentTime = 0;
    setProg({ t: 0, d: 0 });
    a.play().catch(() => setCur(null));
    setCur(id);
  }, [cur]);
  const stop = useCallback(() => { audioRef.current && audioRef.current.pause(); setCur(null); }, []);
  const seek = useCallback(frac => {
    const a = audioRef.current;
    if (a && a.duration) a.currentTime = frac * a.duration;
  }, []);

  return <AsAudioCtx.Provider value={{ cur, prog, toggle, stop, seek }}>{children}</AsAudioCtx.Provider>;
}

function AsPlayButton({ id, src, size }) {
  const { cur, toggle } = useContext(AsAudioCtx);
  const on = cur === id;
  return (
    <button className={"as-play" + (on ? " on" : "")} style={size ? { width: size, height: size } : null}
      title={on ? "Stop" : "Play"} onClick={e => { e.stopPropagation(); toggle(id, src); }}>
      {on
        ? <svg viewBox="0 0 12 12" width="11" height="11"><rect x="2" y="2" width="3" height="8" fill="currentColor"/><rect x="7" y="2" width="3" height="8" fill="currentColor"/></svg>
        : <svg viewBox="0 0 12 12" width="11" height="11"><path d="M3 1.5v9l7.5-4.5z" fill="currentColor"/></svg>}
    </button>
  );
}

function AsProgress({ id }) {
  const { cur, prog, seek } = useContext(AsAudioCtx);
  if (cur !== id) return null;
  const pct = prog.d ? (prog.t / prog.d) * 100 : 0;
  return (
    <div className="as-prog" onClick={e => {
      const r = e.currentTarget.getBoundingClientRect();
      seek((e.clientX - r.left) / r.width);
    }}>
      <div className="as-prog-fill" style={{ width: pct + "%" }}/>
      <span className="as-prog-time">{fmtTime(prog.t)} / {fmtTime(prog.d)}</span>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtTime(s) {
  if (!s || !isFinite(s)) return "0:00";
  const m = Math.floor(s / 60), r = Math.floor(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
}
function assetUrl(rel, bust)   { return rel ? `/asset-files/${rel}${bust ? `?v=${bust}` : ""}` : null; }
function libraryUrl(rel, bust) { return rel ? `/library-files/${rel}${bust ? `?v=${bust}` : ""}` : null; }

function UsedBy({ list }) {
  const n = (list || []).length;
  return (
    <span className={"as-used" + (n ? "" : " none")} title={n ? list.join("\n") : "Not used by any project yet"}>
      {n ? `${n} project${n === 1 ? "" : "s"}` : "unused"}
    </span>
  );
}

function AsDrawer({ title, subtitle, onClose, children, footer }) {
  useEffect(() => {
    const k = e => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="as-drawer-bg" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <aside className="as-drawer">
        <div className="as-drawer-hdr">
          <div style={{minWidth:0}}>
            <h3>{title}</h3>
            {subtitle && <div className="as-drawer-sub">{subtitle}</div>}
          </div>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="as-drawer-body">{children}</div>
        {footer && <div className="as-drawer-foot">{footer}</div>}
      </aside>
    </div>
  );
}

function AsField({ label, hint, children }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint && <div className="set-help">{hint}</div>}
    </div>
  );
}

function AsFilePick({ accept, label, file, onFile }) {
  const ref = useRef(null);
  const [over, setOver] = useState(false);
  return (
    <div className={"sample-drop" + (over ? " dragover" : "")}
      onClick={() => ref.current.click()}
      onDragOver={e => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={e => { e.preventDefault(); setOver(false); if (e.dataTransfer.files[0]) onFile(e.dataTransfer.files[0]); }}>
      <div className="sample-drop-text">
        {file ? <><strong>{file.name}</strong> · {(file.size / 1048576).toFixed(1)} MB — click to change</>
              : <>Drop a file here or <strong>browse</strong> · {label}</>}
      </div>
      <input ref={ref} type="file" accept={accept} style={{display:"none"}}
        onChange={e => { if (e.target.files[0]) onFile(e.target.files[0]); e.target.value = ""; }}/>
    </div>
  );
}

const PAID_NOTE = "This calls fal.ai and costs credits.";

// ── Characters ────────────────────────────────────────────────────────────────

// Image slots of a character — each can be filled by uploading a file
// (POST /assets/characters/<name>/image/<slot>). The scene reference is the image
// used to keep the character on-model in every scene.
const CHAR_SLOTS = [
  { slot: "scene_reference", field: "art_34left_file_path",  label: "Scene reference", hint: "Full body, 3/4 left — used in every scene image" },
  { slot: "thumbnail",       field: "thumbnail_file_path",   label: "Thumbnail",       hint: "Small portrait" },
  { slot: "drawing",         field: "ref_drawing_file_path", label: "Hand-made drawing", hint: "Input for series-style art" },
  { slot: "turnaround",      field: "artwork_file_path",     label: "Turnaround",      hint: "Front / side / back sheet" },
  { slot: "reference",       field: "ref_image_file_path",   label: "Reference image", hint: "Single-image reference (animals, story characters)" },
];

function CharImageSlot({ name, def, rel, bust, reload }) {
  const { toast } = useApp();
  const inputRef = useRef(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  async function upload(file) {
    if (!file) return;
    if (!file.type.startsWith("image/")) { toast("Not an image", file.name, "err"); return; }
    const fd = new FormData(); fd.append("file", file);
    setBusy(true);
    try {
      await apiPostForm(`/assets/characters/${encodeURIComponent(name)}/image/${def.slot}`, fd);
      toast("Uploaded", `${def.label} of ${name} updated.`, "ok");
      await reload();
    } catch (e) { toast("Error", e.message, "err"); }
    setBusy(false);
  }
  return (
    <div className={"as-slot" + (rel ? "" : " as-slot-empty") + (over ? " over" : "")} title={def.hint}
      onDragOver={e => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={e => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files[0]); }}>
      <div className="as-slot-pic" onClick={() => rel ? window.open(assetUrl(rel, bust), "_blank") : inputRef.current.click()}>
        {rel ? <img src={assetUrl(rel, bust)} alt={def.label}/> : <span>{busy ? "…" : "+ Add"}</span>}
      </div>
      <div className="as-slot-foot">
        <span>{def.label}</span>
        {rel && <button className="as-slot-btn" disabled={busy} onClick={() => inputRef.current.click()}>{busy ? "…" : "Replace"}</button>}
      </div>
      <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" style={{display:"none"}}
        onChange={e => { upload(e.target.files[0]); e.target.value = ""; }}/>
    </div>
  );
}

// Card cover: full-body art first so the grid looks consistent.
const COVER_ORDER = ["art_34left_file_path", "ref_image_file_path", "ref_drawing_file_path",
                     "thumbnail_file_path", "artwork_file_path", "concept_art_file_path"];
function charCover(c) {
  for (const f of COVER_ORDER) if (c[f]) return c[f];
  return null;
}

function CharactersPane({ q, usage, adding, setAdding, reload, data, bust }) {
  const [sel, setSel] = useState(null);
  const keys = Object.keys(data).sort((a, b) => a.localeCompare(b))
    .filter(k => !q || `${k} ${data[k].fixed_description || ""} ${data[k].description || ""}`.toLowerCase().includes(q));
  return (
    <>
      <div className="as-grid">
        {keys.map(k => {
          const c = data[k];
          const cover = charCover(c);
          return (
            <div key={k} className="as-card" onClick={() => setSel(k)}>
              <div className="as-thumb char">
                {cover ? <img src={assetUrl(cover, bust)} alt={k} loading="lazy"/>
                       : <span className="as-initial">{k.slice(0, 1)}</span>}
              </div>
              <div className="as-card-body">
                <div className="as-card-title">{k}</div>
                <div className="as-card-sub">{c.fixed_description || c.description || "—"}</div>
                <div className="as-card-meta">
                  <UsedBy list={usage[k]}/>
                  {!c.voice_id && <span className="as-warn" title="No ElevenLabs voice id">no voice</span>}
                </div>
              </div>
            </div>
          );
        })}
        {!keys.length && <div className="as-empty">No characters{q ? " match" : " yet"}.</div>}
      </div>
      {sel && data[sel] && <CharacterDrawer name={sel} c={data[sel]} usage={usage[sel]} bust={bust}
                              onClose={() => setSel(null)} reload={reload}/>}
      {adding && <CharacterDrawer isNew onClose={() => setAdding(false)} reload={reload}
                   onCreated={n => { setAdding(false); setSel(n); }}/>}
    </>
  );
}

function CharacterDrawer({ name, c, usage, isNew, onClose, reload, onCreated, bust }) {
  const { toast, loadAssets } = useApp();
  const blank = { name: "", voice_id: "", fixed_description: "", variable_description: "", height_cm: "", ref_desc: "" };
  const [f, setF] = useState(isNew ? blank : {
    voice_id: c.voice_id || "", fixed_description: c.fixed_description || "",
    variable_description: c.variable_description || "", height_cm: c.height_cm || "", ref_desc: c.ref_desc || "",
  });
  const [busy, setBusy] = useState(false);
  const set = k => e => setF(p => ({ ...p, [k]: e.target.value }));

  async function save() {
    setBusy(true);
    try {
      const body = { ...f, height_cm: f.height_cm ? parseInt(f.height_cm, 10) : null };
      if (isNew) {
        await apiPost("/assets/characters", body);
        toast("Added", f.name, "ok");
        await reload(); loadAssets();
        onCreated(f.name.trim());
      } else {
        await apiPut(`/assets/characters/${encodeURIComponent(name)}`, body);
        toast("Saved", name, "ok");
        await reload(); loadAssets();
      }
    } catch (e) { toast("Error", e.message, "err"); }
    setBusy(false);
  }
  async function remove() {
    if (!confirm(`Delete character “${name}”? Its art files stay on disk.`)) return;
    try { await apiDelete(`/assets/characters/${encodeURIComponent(name)}`); await reload(); loadAssets(); onClose(); }
    catch (e) { toast("Error", e.message, "err"); }
  }
  return (
    <AsDrawer title={isNew ? "New character" : name} subtitle={!isNew && <UsedBy list={usage}/>} onClose={onClose}
      footer={<>
        {!isNew && <button className="btn-edit" onClick={remove}>Delete</button>}
        <div style={{flex:1}}/>
        <button className="btn-cancel" onClick={onClose}>Close</button>
        <button className="btn-primary" disabled={busy || (isNew && !f.name.trim())} onClick={save}>{busy ? "Saving…" : isNew ? "Create" : "Save"}</button>
      </>}>
      {!isNew && (
        <>
          <div className="as-slots">
            {CHAR_SLOTS.map(d => <CharImageSlot key={d.slot} name={name} def={d} rel={c[d.field]} bust={bust} reload={reload}/>)}
          </div>
          <div className="set-help" style={{marginTop:"-.4rem"}}>
            Click an empty slot or drop an image on any slot to set it. Replaced files are kept in the character's <code>previous/</code> folder.
          </div>
        </>
      )}
      {isNew && <div className="set-help">Create the character first — then you can upload its images or generate them.</div>}
      {!isNew && <StyledArtPanel name={name} bust={bust} reload={reload}/>}
      <div className="fields">
        {isNew && <AsField label="Name"><input value={f.name} onChange={set("name")} placeholder="e.g. Zahra"/></AsField>}
        <AsField label="Fixed description" hint="Identity — never changes (age, origin, face, hair).">
          <textarea rows={3} value={f.fixed_description} onChange={set("fixed_description")}/></AsField>
        <AsField label="Default outfit" hint="What they wear unless a scene says otherwise.">
          <textarea rows={2} value={f.variable_description} onChange={set("variable_description")}/></AsField>
        <div className="field-row">
          <AsField label="ElevenLabs voice id"><input value={f.voice_id} onChange={set("voice_id")}/></AsField>
          <AsField label="Height (cm)"><input type="number" value={f.height_cm} onChange={set("height_cm")}/></AsField>
        </div>
        <AsField label="Short reference note" hint="Distinctive cue used in prompts, e.g. “teal blouse, wavy hair”.">
          <input value={f.ref_desc} onChange={set("ref_desc")}/></AsField>
      </div>
    </AsDrawer>
  );
}

// Generate the character "in the series style": fal edit model gets the hand-made
// drawing + one image of the chosen existing characters side by side + the prompt.
// Results land as candidates; nothing is replaced until one is accepted.
const STYLED_SIZES = [["portrait_4_3", "Portrait 3:4"], ["portrait_16_9", "Portrait 9:16"],
                      ["square_hd", "Square"], ["landscape_16_9", "Landscape 16:9 (turnaround)"]];
const TARGET_LABELS = { scene_reference: "Use as scene reference", thumbnail: "Use as thumbnail", turnaround: "Use as turnaround" };

function StyledArtPanel({ name, bust, reload }) {
  const { toast, startPoll } = useApp();
  const [open, setOpen]     = useState(false);
  const [setup, setSetup]   = useState(null);
  const [models, setModels] = useState({ models: [], default_key: null });
  const [chosen, setChosen] = useState([]);
  const [model, setModel]   = useState("");
  const [size, setSize]     = useState("portrait_4_3");
  const [prompt, setPrompt] = useState("");
  const [running, setRunning] = useState(false);
  const [sampleKey, setSampleKey] = useState("");
  const enc = encodeURIComponent(name);

  const load = useCallback(async (keepChoices) => {
    const d = await apiGet(`/assets/characters/${enc}/styled-art`);
    setSetup(d);
    if (!keepChoices) {
      setChosen(d.style_candidates.filter(x => x.default).map(x => x.name));
      setPrompt(d.prompt);
    }
  }, [enc]);
  useEffect(() => {
    if (!open || setup) return;
    load(false).catch(e => toast("Error", e.message, "err"));
    fetchImageModels().then(m => { setModels(m); setModel(m.default_key || (m.models[0] || {}).key || ""); });
  }, [open]);
  // Debounce the sample preview so ticking several characters renders it once.
  useEffect(() => { const t = setTimeout(() => setSampleKey(chosen.join(",")), 400); return () => clearTimeout(t); }, [chosen]);

  function toggle(n) { setChosen(p => p.includes(n) ? p.filter(x => x !== n) : [...p, n]); }

  async function generate() {
    const ep = (models.models.find(m => m.key === model) || {}).endpoint || model;
    if (!confirm(`Generate “${name}” with ${model}?\n\nSends ${setup.drawing ? "the drawing + " : ""}a style sample of ${chosen.length} character(s) to ${ep}.\n${PAID_NOTE}`)) return;
    setRunning(true);
    try {
      const d = await apiPost(`/assets/characters/${enc}/styled-art`, { model, prompt, chars: chosen, image_size: size });
      startPoll("assets", d.step_key, async st => {
        setRunning(false);
        if (st.status === "error") toast("Generation failed", st.log || "", "err");
        else { toast("Done", "New candidate below — accept it to use it.", "ok"); await load(true); await reload(); }
      });
    } catch (e) { setRunning(false); toast("Error", e.message, "err"); }
  }
  async function accept(path, target) {
    try { await apiPost(`/assets/characters/${enc}/candidates/accept`, { path, target }); await load(true); await reload(); toast("Saved", TARGET_LABELS[target].replace("Use as ", "") + " updated.", "ok"); }
    catch (e) { toast("Error", e.message, "err"); }
  }
  async function discard(path) {
    if (!confirm("Discard this candidate?")) return;
    try { await apiPost(`/assets/characters/${enc}/candidates/discard`, { path }); await load(true); }
    catch (e) { toast("Error", e.message, "err"); }
  }

  if (!open) {
    return <button className="btn-ghost sa-open" onClick={() => setOpen(true)}>✦ Generate art in the series style…</button>;
  }
  if (!setup) return <div className="sa-panel"><div className="as-empty">Loading…</div></div>;

  const current = setup.style_candidates;
  return (
    <div className="sa-panel">
      <div className="sa-head">
        <strong>Generate in the series style</strong>
        <button className="modal-close" onClick={() => setOpen(false)}>✕</button>
      </div>

      <div className="sa-sent">
        <div className="sa-slot">
          <label>1 · Hand-made drawing</label>
          {setup.drawing ? <img src={assetUrl(setup.drawing, bust)} alt="drawing"/>
                         : <div className="sa-missing">No drawing yet — upload one above for the best result (otherwise the model works from the description).</div>}
        </div>
        <div className="sa-slot wide">
          <label>2 · Style sample ({chosen.length} characters)</label>
          {sampleKey ? <img src={`/assets/characters/${enc}/style-sample.png?chars=${encodeURIComponent(sampleKey)}`} alt="style sample"/>
                     : <div className="sa-missing">Pick at least one character below.</div>}
        </div>
      </div>

      <div className="sa-chips">
        {current.map(x => (
          <button key={x.name} className={"sa-chip" + (chosen.includes(x.name) ? " on" : "")} onClick={() => toggle(x.name)} title={x.name}>
            <img src={assetUrl(x.path, bust)} alt=""/><span>{x.name}</span>
          </button>
        ))}
      </div>

      <div className="field-row" style={{marginTop:".7rem"}}>
        <AsField label="Model">
          <select value={model} onChange={e => setModel(e.target.value)}>
            {models.models.map(m => <option key={m.key} value={m.key}>{m.key}</option>)}
          </select>
        </AsField>
        <AsField label="Image size">
          <select value={size} onChange={e => setSize(e.target.value)}>
            {STYLED_SIZES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </AsField>
      </div>
      <AsField label="3 · Prompt" hint={<>Models come from Settings → All settings → [fal_models]. <a href="#" onClick={e => { e.preventDefault(); setPrompt(setup.prompt); }}>Reset prompt</a></>}>
        <textarea rows={7} value={prompt} onChange={e => setPrompt(e.target.value)}/>
      </AsField>
      <div className="edit-actions">
        <button className="btn-primary" disabled={running || !chosen.length || !prompt.trim()} onClick={generate}>
          {running ? "Generating… (≈20–60 s)" : "Generate (paid)"}
        </button>
      </div>

      {setup.candidates.length > 0 && (
        <div className="sa-cands">
          <label>Candidates</label>
          {setup.candidates.map(cd => {
            const inUse = Object.keys(TARGET_LABELS).filter(t => (setup.in_use || {})[t] === cd.path);
            return (
              <div key={cd.path} className="sa-cand">
                <a href={assetUrl(cd.path)} target="_blank" rel="noreferrer"><img src={assetUrl(cd.path)} alt=""/></a>
                <div className="sa-cand-info">
                  <div className="set-help">{cd.model} · {cd.created.replace("_", " ")} · {cd.style_sample.length} style refs{cd.used_drawing ? " + drawing" : ""}</div>
                  <div className="sa-cand-btns">
                    {Object.keys(TARGET_LABELS).map(t => inUse.includes(t)
                      ? <span key={t} className="as-used">✓ {t.replace("_", " ")}</span>
                      : <button key={t} className="btn-edit" onClick={() => accept(cd.path, t)}>{TARGET_LABELS[t]}</button>)}
                    <button className="btn-edit" onClick={() => discard(cd.path)}>Discard</button>
                    <button className="btn-edit" onClick={() => setPrompt(cd.prompt)} title="Load the prompt used for this candidate">Reuse prompt</button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Locations ─────────────────────────────────────────────────────────────────

function LocationsPane({ q, usage, adding, setAdding, reload, data, bust }) {
  const [sel, setSel] = useState(null);
  const keys = Object.keys(data).sort()
    .filter(k => !q || `${k} ${data[k].description || ""}`.toLowerCase().includes(q));
  return (
    <>
      <div className="as-grid wide">
        {keys.map(k => (
          <div key={k} className="as-card" onClick={() => setSel(k)}>
            <div className="as-thumb loc">
              {data[k].artwork_file_path ? <img src={assetUrl(data[k].artwork_file_path, bust)} alt={k} loading="lazy"/>
                                         : <span className="as-initial">⌂</span>}
            </div>
            <div className="as-card-body">
              <div className="as-card-title">{k}</div>
              <div className="as-card-sub">{data[k].description || "—"}</div>
              <div className="as-card-meta"><UsedBy list={usage[k]}/></div>
            </div>
          </div>
        ))}
        {!keys.length && <div className="as-empty">No locations{q ? " match" : " yet"}. Locations are optional — by default each project describes its own setting.</div>}
      </div>
      {sel && data[sel] && <LocationDrawer k={sel} l={data[sel]} usage={usage[sel]} bust={bust} onClose={() => setSel(null)} reload={reload}/>}
      {adding && <LocationDrawer isNew onClose={() => setAdding(false)} reload={reload} onCreated={k => { setAdding(false); setSel(k); }}/>}
    </>
  );
}

function LocationDrawer({ k, l, usage, isNew, onClose, reload, onCreated, bust }) {
  const { toast, loadAssets } = useApp();
  const [f, setF] = useState(isNew ? { key: "", description: "", creation_prompt: "" }
                                   : { description: l.description || "", creation_prompt: l.creation_prompt || "" });
  const [busy, setBusy] = useState(false);
  const set = n => e => setF(p => ({ ...p, [n]: e.target.value }));
  async function save() {
    setBusy(true);
    try {
      if (isNew) { await apiPost("/assets/locations", f); await reload(); loadAssets(); onCreated(f.key.trim()); }
      else { await apiPut(`/assets/locations/${k}`, f); toast("Saved", k, "ok"); await reload(); }
    } catch (e) { toast("Error", e.message, "err"); }
    setBusy(false);
  }
  async function remove() {
    if (!confirm(`Delete location “${k}”? Its image stays on disk.`)) return;
    try { await apiDelete(`/assets/locations/${k}`); await reload(); loadAssets(); onClose(); }
    catch (e) { toast("Error", e.message, "err"); }
  }
  async function genArt() {
    if (!confirm(`Generate the background for “${k}”?\n\n${PAID_NOTE}`)) return;
    try { await apiPost(`/assets/locations/${k}/generate-art`, {}); toast("Started", "Generating in the background — reopen in a minute.", "ok"); }
    catch (e) { toast("Error", e.message, "err"); }
  }
  return (
    <AsDrawer title={isNew ? "New location" : k} subtitle={!isNew && <UsedBy list={usage}/>} onClose={onClose}
      footer={<>
        {!isNew && <button className="btn-edit" onClick={remove}>Delete</button>}
        <div style={{flex:1}}/>
        <button className="btn-cancel" onClick={onClose}>Close</button>
        <button className="btn-primary" disabled={busy || (isNew && (!f.key.trim() || !f.description.trim() || !f.creation_prompt.trim()))} onClick={save}>
          {busy ? "Saving…" : isNew ? "Create" : "Save"}</button>
      </>}>
      {!isNew && l.artwork_file_path && <img className="as-hero" src={assetUrl(l.artwork_file_path, bust)} alt={k}/>}
      {!isNew && <div className="edit-actions" style={{marginTop:0}}>
        <button className="btn-ghost" onClick={genArt} title={PAID_NOTE}>{l.artwork_file_path ? "Regenerate background (paid)" : "Generate background (paid)"}</button>
      </div>}
      <div className="fields">
        {isNew && <AsField label="Key"><input value={f.key} onChange={set("key")} placeholder="e.g. bakery"/></AsField>}
        <AsField label="Scene description" hint="Used in script prompts: where the characters are and what they wear.">
          <textarea rows={4} value={f.description} onChange={set("description")}/></AsField>
        <AsField label="Background art prompt" hint="Prompt for the empty background image.">
          <textarea rows={4} value={f.creation_prompt} onChange={set("creation_prompt")}/></AsField>
      </div>
    </AsDrawer>
  );
}

// ── Music ─────────────────────────────────────────────────────────────────────

const LICENSES = [
  { id: "YTsafe",     label: "YouTube" },
  { id: "Metasafe",   label: "Meta" },
  { id: "TikToksafe", label: "TikTok" },
];

function LoudnessBar({ db }) {
  if (db === undefined || db === null) return <span className="as-loud none">—</span>;
  // -60 dB (silent) … -10 dB (very loud) mapped to 0…100 %
  const pct = Math.max(4, Math.min(100, ((db + 60) / 50) * 100));
  const tone = db < -38 ? "quiet" : db > -16 ? "loud" : "ok";
  return (
    <span className={"as-loud " + tone} title={`Average level ${db.toFixed(1)} dB`}>
      <span className="as-loud-bar"><span style={{ width: pct + "%" }}/></span>
      {db.toFixed(0)} dB
    </span>
  );
}

function MusicPane({ q, usage, adding, setAdding, reload, data }) {
  const { toast } = useApp();
  const [lic, setLic]   = useState("all");
  const [sort, setSort] = useState("name");
  const [edit, setEdit] = useState(null);
  const [tool, setTool] = useState(null);

  let keys = Object.keys(data).filter(k => {
    const t = data[k];
    if (q && !`${k} ${t.description || ""}`.toLowerCase().includes(q)) return false;
    if (lic === "none") return !t.license;
    if (lic !== "all") return t.license === lic;
    return true;
  });
  const used = k => (usage[k] || []).length;
  keys.sort(sort === "used" ? (a, b) => used(b) - used(a) || a.localeCompare(b)
          : sort === "loud" ? (a, b) => ((data[a].loudness || {}).mean_db ?? -99) - ((data[b].loudness || {}).mean_db ?? -99)
          : (a, b) => a.localeCompare(b));

  return (
    <>
      <div className="as-filters">
        {[["all", "All"], ...LICENSES.map(l => [l.id, l.label + "-safe"]), ["none", "No license tag"]].map(([id, label]) => (
          <button key={id} className={"as-chip" + (lic === id ? " on" : "")} onClick={() => setLic(id)}>{label}</button>
        ))}
        <select className="as-sort" value={sort} onChange={e => setSort(e.target.value)}>
          <option value="name">Sort: name</option>
          <option value="used">Sort: most used</option>
          <option value="loud">Sort: quietest first</option>
        </select>
      </div>
      <div className="as-list">
        {keys.map(k => {
          const t = data[k];
          return (
            <div key={k} className="as-row">
              <AsPlayButton id={`m:${k}`} src={libraryUrl(t.full_path, t.gain_db)}/>
              <div className="as-row-main">
                <div className="as-row-title">
                  {k}
                  {t.license && <span className={"as-lic " + t.license}>{(LICENSES.find(l => l.id === t.license) || {}).label || t.license}</span>}
                  {t.gain_db ? <span className="as-gain" title="Volume adjusted relative to the original upload">{t.gain_db > 0 ? "+" : ""}{t.gain_db} dB</span> : null}
                </div>
                <div className="as-row-sub">{t.description || <em>No description</em>}</div>
                <AsProgress id={`m:${k}`}/>
              </div>
              <span className="as-dur">{t.loudness ? fmtTime(t.loudness.duration_s) : ""}</span>
              <LoudnessBar db={t.loudness && t.loudness.mean_db}/>
              <UsedBy list={usage[k]}/>
              <button className="btn-ghost as-row-btn" onClick={() => setTool(k)}>Volume</button>
              <button className="btn-edit" onClick={() => setEdit(k)}>Edit</button>
            </div>
          );
        })}
        {!keys.length && <div className="as-empty">No tracks match.</div>}
      </div>
      {edit && data[edit] && <MusicEditDrawer k={edit} t={data[edit]} usage={usage[edit]} onClose={() => setEdit(null)} reload={reload}/>}
      {tool && data[tool] && <VolumeTool k={tool} usage={usage[tool]} onClose={() => setTool(null)} reload={reload}/>}
      {adding && <MusicAddDrawer onClose={() => setAdding(false)} reload={reload}
                   onAdded={k => { setAdding(false); setTool(k); toast("Added", `Now check its volume.`, "ok"); }}/>}
    </>
  );
}

function MusicEditDrawer({ k, t, usage, onClose, reload }) {
  const { toast } = useApp();
  const [f, setF] = useState({ description: t.description || "", license: t.license || "" });
  async function save() {
    try { await apiPut(`/assets/background-audio/${k}`, f); toast("Saved", k, "ok"); await reload(); onClose(); }
    catch (e) { toast("Error", e.message, "err"); }
  }
  async function remove() {
    const n = (usage || []).length;
    if (!confirm(`Delete track “${k}” and its file?${n ? `\n\n${n} project(s) use it and would render without music.` : ""}`)) return;
    try { await apiDelete(`/assets/background-audio/${k}?delete_file=1`); await reload(); onClose(); }
    catch (e) { toast("Error", e.message, "err"); }
  }
  return (
    <AsDrawer title={k} subtitle={<UsedBy list={usage}/>} onClose={onClose}
      footer={<><button className="btn-edit" onClick={remove}>Delete</button><div style={{flex:1}}/>
        <button className="btn-cancel" onClick={onClose}>Close</button><button className="btn-primary" onClick={save}>Save</button></>}>
      <div className="fields">
        <AsField label="Description"><textarea rows={3} value={f.description} onChange={e => setF(p => ({ ...p, description: e.target.value }))}/></AsField>
        <AsField label="Safe to use on" hint="Tracks are picked per platform when assembling (YouTube / Meta / TikTok variants).">
          <select value={f.license} onChange={e => setF(p => ({ ...p, license: e.target.value }))}>
            <option value="">— not tagged —</option>
            {LICENSES.map(l => <option key={l.id} value={l.id}>{l.label}</option>)}
          </select>
        </AsField>
        <div className="set-meta"><span>File: <code>library/{t.full_path}</code></span>{t.original_path && <span>Original: <code>library/{t.original_path}</code></span>}</div>
        {usage && usage.length > 0 && <div className="as-usedlist"><label>Used by</label>{usage.map(p => <span key={p} className="tag">{p}</span>)}</div>}
      </div>
    </AsDrawer>
  );
}

function MusicAddDrawer({ onClose, reload, onAdded }) {
  const { toast } = useApp();
  const [file, setFile] = useState(null);
  const [f, setF] = useState({ key: "", description: "", license: "" });
  const [busy, setBusy] = useState(false);
  function pick(fl) {
    setFile(fl);
    if (!f.key) setF(p => ({ ...p, key: fl.name.replace(/\.[^.]+$/, "").toLowerCase().replace(/[^a-z0-9_-]+/g, "_") }));
  }
  async function upload() {
    const fd = new FormData();
    fd.append("file", file); Object.entries(f).forEach(([k, v]) => fd.append(k, v));
    setBusy(true);
    try { const d = await apiPostForm("/assets/background-audio", fd); await reload(); onAdded(d.track.name); }
    catch (e) { toast("Error", e.message, "err"); }
    setBusy(false);
  }
  return (
    <AsDrawer title="Add background music" subtitle="Shared by every workspace" onClose={onClose}
      footer={<><div style={{flex:1}}/><button className="btn-cancel" onClick={onClose}>Cancel</button>
        <button className="btn-primary" disabled={busy || !file || !f.key.trim()} onClick={upload}>{busy ? "Uploading…" : "Upload"}</button></>}>
      <div className="fields">
        <AsFilePick accept=".mp3,.mp4,.m4a,.wav,.ogg,.aac,.flac,.mov,.webm,audio/*,video/mp4" label="MP3, MP4 (audio is extracted), WAV, M4A…"
          file={file} onFile={pick}/>
        <AsField label="Name (key)" hint="How projects refer to this track."><input value={f.key} onChange={e => setF(p => ({ ...p, key: e.target.value }))}/></AsField>
        <AsField label="Description"><textarea rows={2} value={f.description} onChange={e => setF(p => ({ ...p, description: e.target.value }))}/></AsField>
        <AsField label="Safe to use on">
          <select value={f.license} onChange={e => setF(p => ({ ...p, license: e.target.value }))}>
            <option value="">— not tagged —</option>
            {LICENSES.map(l => <option key={l.id} value={l.id}>{l.label}</option>)}
          </select>
        </AsField>
        <div className="set-help">After uploading you can raise or lower its volume and listen to a slice before saving.</div>
      </div>
    </AsDrawer>
  );
}

// Listen to a slice from the middle of a track at a new volume (optionally under a
// spoken line, mixed the way the assembler does), then bake the gain into the file.
function VolumeTool({ k, usage, onClose, reload }) {
  const { toast } = useApp();
  const { stop } = useContext(AsAudioCtx);
  const [info, setInfo]   = useState(null);
  const [gain, setGain]   = useState(0);
  const [voice, setVoice] = useState(false);
  const [busy, setBusy]   = useState(false);
  const [playing, setPlaying] = useState(null);     // "before" | "after"
  const [loading, setLoading] = useState(false);
  const audioRef = useRef(null);

  useEffect(() => {
    stop();
    apiGet(`/assets/background-audio/${k}/analyze`).then(d => { setInfo(d); setGain(d.track.gain_db || 0); })
      .catch(e => toast("Error", e.message, "err"));
    return () => { if (audioRef.current) audioRef.current.pause(); };
  }, [k]);

  if (!info) return <AsDrawer title={`Volume · ${k}`} onClose={onClose}><div className="as-empty">Measuring loudness…</div></AsDrawer>;

  const t = info.track;
  const baseGain = t.gain_db || 0;
  const orig = t.original_loudness || t.loudness;            // level of the untouched upload
  const origMean = t.original_loudness ? orig.mean_db : orig.mean_db - baseGain;
  const origPeak = t.original_loudness ? orig.peak_db : orig.peak_db - baseGain;
  const newMean = origMean + gain, newPeak = origPeak + gain;
  const median = info.library_median_mean_db;
  const changed = Math.abs(gain - baseGain) > 0.05;

  function play(which) {
    const a = audioRef.current;
    if (playing === which) { a.pause(); setPlaying(null); return; }
    const g = which === "before" ? baseGain : gain;
    a.src = `/assets/background-audio/${k}/preview?gain_db=${g}&seconds=15${voice ? "&voice=1" : ""}&t=${Date.now()}`;
    setLoading(true);
    a.play().then(() => { setPlaying(which); setLoading(false); }).catch(() => { setPlaying(null); setLoading(false); });
  }
  async function apply() {
    setBusy(true);
    try {
      await apiPost(`/assets/background-audio/${k}/apply-gain`, { gain_db: gain });
      toast("Saved", `${k} is now ${gain > 0 ? "+" : ""}${gain.toFixed(1)} dB vs. the original.`, "ok");
      await reload(); onClose();
    } catch (e) { toast("Error", e.message, "err"); }
    setBusy(false);
  }

  return (
    <AsDrawer title={`Volume · ${k}`} subtitle="Preview a 15-second slice from the middle of the track" onClose={onClose}
      footer={<><div style={{flex:1}}/><button className="btn-cancel" onClick={onClose}>Close</button>
        <button className="btn-primary" disabled={busy || !changed} onClick={apply}>{busy ? "Saving…" : `Save at ${gain > 0 ? "+" : ""}${gain.toFixed(1)} dB`}</button></>}>
      <audio ref={audioRef} onEnded={() => setPlaying(null)} style={{display:"none"}}/>
      <div className="vt-stats">
        <div><label>Original average</label><strong>{origMean.toFixed(1)} dB</strong></div>
        <div><label>Saved now</label><strong>{baseGain > 0 ? "+" : ""}{baseGain.toFixed(1)} dB</strong></div>
        <div><label>Library average</label><strong>{median !== null && median !== undefined ? `${median.toFixed(1)} dB` : "—"}</strong></div>
      </div>

      {info.typical_video_gain_db !== null && info.typical_video_gain_db !== undefined && (
        <div className="set-help">
          In a video this file needs about <strong style={{color:"var(--text)"}}>{info.typical_video_gain_db > 0 ? "+" : ""}{info.typical_video_gain_db} dB</strong> of
          project gain to sit {info.music_below_voice_db} dB under typical voices — the Assemble step suggests the exact value per project.
          Saving a louder/quieter file here lowers/raises that number by the same amount.
        </div>
      )}
      <div className="vt-slider">
        <div className="vt-gain">{gain > 0 ? "+" : ""}{gain.toFixed(1)} <span>dB</span></div>
        <input type="range" min={-20} max={30} step={0.5} value={gain} onChange={e => { setGain(parseFloat(e.target.value)); }}/>
        <div className="vt-scale"><span>−20</span><span>0</span><span>+30</span></div>
        <div className="vt-result">
          New average ≈ <strong>{newMean.toFixed(1)} dB</strong>, peak ≈ <strong>{Math.min(newPeak, -0.3).toFixed(1)} dB</strong>
          {newPeak > -0.3 && <span className="as-warn"> peaks limited (+{(newPeak + 0.3).toFixed(1)} dB squeezed)</span>}
        </div>
        <div className="edit-actions" style={{marginTop:".4rem"}}>
          {median !== null && median !== undefined && (
            <button className="btn-edit" onClick={() => setGain(Math.round((median - origMean) * 2) / 2)}>Match library average</button>)}
          <button className="btn-edit" onClick={() => setGain(baseGain)}>Back to saved</button>
          <button className="btn-edit" onClick={() => setGain(0)}>Original</button>
        </div>
      </div>

      <div className="vt-listen">
        <button className={"vt-btn" + (playing === "before" ? " on" : "")} onClick={() => play("before")} disabled={loading}>
          {playing === "before" ? "■" : "▶"} Saved version
        </button>
        <button className={"vt-btn accent" + (playing === "after" ? " on" : "")} onClick={() => play("after")} disabled={loading}>
          {playing === "after" ? "■" : "▶"} With {gain > 0 ? "+" : ""}{gain.toFixed(1)} dB
        </button>
        {loading && <span className="set-help">Rendering…</span>}
      </div>
      {changed && (usage || []).length > 0 && (
        <div className="vt-warn">
          {usage.length} project{usage.length === 1 ? " was" : "s were"} mixed against the saved level — re-assembling
          {usage.length === 1 ? " it" : " them"} after saving makes the music {Math.abs(gain - baseGain).toFixed(1)} dB {gain > baseGain ? "louder" : "quieter"} there
          (their own gain setting stays as is).
        </div>
      )}
      <label className="toggle-row" title={info.voice_sample ? "" : "No voiced project in this workspace yet"}>
        <input type="checkbox" checked={voice} disabled={!info.voice_sample} onChange={e => setVoice(e.target.checked)}/>
        Play under a spoken line (music at the video's background level, {Math.round(info.bg_audio_volume * 100)}%)
      </label>
      <div className="set-help" style={{marginTop:".6rem"}}>
        The gain is applied to the original upload, so you can come back and change it again without quality loss.
        Projects can still nudge the level per video when assembling.
      </div>
    </AsDrawer>
  );
}

// ── SFX ───────────────────────────────────────────────────────────────────────

function SfxPane({ q, adding, setAdding, reload, data }) {
  const { toast } = useApp();
  const keys = Object.keys(data).sort().filter(k => !q || `${k} ${data[k].description || ""}`.toLowerCase().includes(q));
  async function remove(k) {
    if (!confirm(`Delete SFX “${k}” and its file?`)) return;
    try { await apiDelete(`/assets/sfx/${k}?delete_file=1`); await reload(); } catch (e) { toast("Error", e.message, "err"); }
  }
  return (
    <>
      <div className="as-list">
        {keys.map(k => (
          <div key={k} className="as-row">
            <AsPlayButton id={`s:${k}`} src={libraryUrl(data[k].full_path)}/>
            <div className="as-row-main">
              <div className="as-row-title">{k}</div>
              <div className="as-row-sub">{data[k].description || <em>No description</em>}</div>
              <AsProgress id={`s:${k}`}/>
            </div>
            <button className="btn-edit" onClick={() => remove(k)}>Delete</button>
          </div>
        ))}
        {!keys.length && <div className="as-empty">No sound effects{q ? " match" : " yet"}.</div>}
      </div>
      {adding && <SimpleUploadDrawer title="Add sound effect" endpoint="/assets/sfx" accept="audio/*,.mp3,.wav"
                   label="MP3 or WAV" onClose={() => setAdding(false)} reload={reload}/>}
    </>
  );
}

function SimpleUploadDrawer({ title, endpoint, accept, label, onClose, reload }) {
  const { toast } = useApp();
  const [file, setFile] = useState(null);
  const [f, setF] = useState({ key: "", description: "" });
  const [busy, setBusy] = useState(false);
  async function upload() {
    const fd = new FormData(); fd.append("file", file); fd.append("key", f.key); fd.append("description", f.description);
    setBusy(true);
    try { await apiPostForm(endpoint, fd); toast("Added", f.key, "ok"); await reload(); onClose(); }
    catch (e) { toast("Error", e.message, "err"); }
    setBusy(false);
  }
  return (
    <AsDrawer title={title} onClose={onClose}
      footer={<><div style={{flex:1}}/><button className="btn-cancel" onClick={onClose}>Cancel</button>
        <button className="btn-primary" disabled={busy || !file || !f.key.trim()} onClick={upload}>{busy ? "Uploading…" : "Upload"}</button></>}>
      <div className="fields">
        <AsFilePick accept={accept} label={label} file={file}
          onFile={fl => { setFile(fl); if (!f.key) setF(p => ({ ...p, key: fl.name.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_-]+/g, "_") })); }}/>
        <AsField label="Name (key)"><input value={f.key} onChange={e => setF(p => ({ ...p, key: e.target.value }))}/></AsField>
        <AsField label="Description"><textarea rows={2} value={f.description} onChange={e => setF(p => ({ ...p, description: e.target.value }))}/></AsField>
      </div>
    </AsDrawer>
  );
}

// ── Branding (intro / outro clips) ────────────────────────────────────────────

function BrandingPane({ q, usage, adding, setAdding, reload, clips, files }) {
  const { toast } = useApp();
  const [open, setOpen] = useState(null);           // file name playing with sound in the drawer
  const byFile = {};
  Object.entries(clips).forEach(([k, c]) => { byFile[(c.video_file_path || "").split("/").pop()] = { key: k, ...c }; });
  const missing = Object.values(byFile).filter(c => !files.includes((c.video_file_path || "").split("/").pop()));
  const shown = files.filter(fn => !q || `${fn} ${(byFile[fn] || {}).description || ""}`.toLowerCase().includes(q));

  async function removeClip(c) {
    if (!confirm(`Remove clip “${c.key}”${files.includes((c.video_file_path || "").split("/").pop()) ? " and delete its file" : ""}?`)) return;
    try { await apiDelete(`/assets/video-clips/${c.key}?delete_file=1`); await reload(); } catch (e) { toast("Error", e.message, "err"); }
  }
  return (
    <>
      <p className="set-intro">Clips in <code>assets/branding/</code> can be added as intro / outro when assembling a video.</p>
      <div className="as-grid wide">
        {shown.map(fn => {
          const c = byFile[fn];
          return (
            <div key={fn} className="as-card" onClick={() => setOpen(fn)}>
              <div className="as-thumb vid">
                <video src={assetUrl(`branding/${fn}`) + "#t=1"} muted preload="metadata" playsInline
                  onMouseEnter={e => { e.target.play().catch(() => {}); }}
                  onMouseLeave={e => { e.target.pause(); }}/>
                <span className="as-vid-badge">▶</span>
              </div>
              <div className="as-card-body">
                <div className="as-card-title">{c ? c.key : fn}</div>
                <div className="as-card-sub">{c ? (c.description || fn) : fn}</div>
                <div className="as-card-meta"><UsedBy list={usage[fn]}/></div>
              </div>
            </div>
          );
        })}
        {!shown.length && <div className="as-empty">No branding clips{q ? " match" : " yet"}.</div>}
      </div>
      {missing.length > 0 && (
        <div className="as-missing">
          <strong>Registered clips with a missing file:</strong>
          {missing.map(c => (
            <span key={c.key} className="as-missing-item">{c.key} → {c.video_file_path}
              <button className="btn-edit" onClick={() => removeClip(c)}>Remove entry</button></span>
          ))}
        </div>
      )}
      {open && (
        <AsDrawer title={byFile[open] ? byFile[open].key : open} subtitle={open} onClose={() => setOpen(null)}
          footer={byFile[open] && <><button className="btn-edit" onClick={() => { removeClip(byFile[open]); setOpen(null); }}>Delete</button><div style={{flex:1}}/></>}>
          <video className="as-hero" src={assetUrl(`branding/${open}`)} controls autoPlay/>
          {byFile[open] && <div className="set-help">{byFile[open].description}</div>}
          {(usage[open] || []).length > 0 && <div className="as-usedlist"><label>Used by</label>{usage[open].map(p => <span key={p} className="tag">{p}</span>)}</div>}
        </AsDrawer>
      )}
      {adding && <SimpleUploadDrawer title="Add branding clip" endpoint="/assets/video-clips" accept="video/*,.mp4,.mov,.webm"
                   label="MP4 intro or outro" onClose={() => setAdding(false)} reload={reload}/>}
    </>
  );
}

// ── The page ──────────────────────────────────────────────────────────────────

const ASSET_TABS = [
  { id: "characters", label: "Characters", add: "Character", shared: false },
  { id: "locations",  label: "Locations",  add: "Location",  shared: false },
  { id: "music",      label: "Music",      add: "Track",     shared: true  },
  { id: "sfx",        label: "SFX",        add: "Sound",     shared: true  },
  { id: "branding",   label: "Branding",   add: "Clip",      shared: false },
];

function AssetsTab() {
  const { workspace } = useApp();
  const [tab, setTab]       = useState(() => { try { return localStorage.getItem("assets.tab") || "characters"; } catch { return "characters"; } });
  const [q, setQ]           = useState("");
  const [adding, setAdding] = useState(false);
  const [usage, setUsage]   = useState({});
  const [data, setData]     = useState({ characters: {}, locations: {}, music: {}, sfx: {}, clips: {}, files: [] });
  const [bust, setBust]     = useState(Date.now());

  const reload = useCallback(async () => {
    const get = u => fetch(u).then(r => r.json()).catch(() => ({}));
    const [characters, locations, music, sfx, clips, files, use] = await Promise.all([
      get("/assets/characters"), get("/assets/locations"), get("/assets/background-audio"),
      get("/assets/sfx"), get("/assets/video-clips"), get("/assets/branding/list"), get("/assets/usage"),
    ]);
    setData({ characters, locations, music, sfx, clips, files: files.files || [] });
    setUsage(use || {});
    setBust(Date.now());
  }, []);
  useEffect(() => { reload(); }, [reload]);
  useEffect(() => { try { localStorage.setItem("assets.tab", tab); } catch {} setQ(""); setAdding(false); }, [tab]);

  const counts = {
    characters: Object.keys(data.characters).length, locations: Object.keys(data.locations).length,
    music: Object.keys(data.music).length, sfx: Object.keys(data.sfx).length, branding: data.files.length,
  };
  const cur = ASSET_TABS.find(t => t.id === tab);
  const needle = q.trim().toLowerCase();
  const common = { q: needle, adding, setAdding, reload };

  return (
    <AsAudioProvider>
      <div className="as-page">
        <div className="as-head">
          <div>
            <h2>Assets</h2>
            <div className="as-head-sub">
              {cur.shared ? "Shared library — available in every workspace"
                          : <>Workspace <strong>{workspace ? workspace.name : ""}</strong></>}
            </div>
          </div>
          <div className="as-tools">
            <input className="pt-filter as-search" placeholder={`Search ${cur.label.toLowerCase()}…`} value={q} onChange={e => setQ(e.target.value)}/>
            <button className="btn-primary" onClick={() => setAdding(true)}>+ {cur.add}</button>
          </div>
        </div>
        <div className="tabs">
          {ASSET_TABS.map(t => (
            <button key={t.id} className={"tab" + (tab === t.id ? " active" : "")} onClick={() => setTab(t.id)}>
              {t.label} <span className="as-count">{counts[t.id]}</span>
            </button>
          ))}
        </div>
        {tab === "characters" && <CharactersPane {...common} data={data.characters} usage={usage.characters || {}} bust={bust}/>}
        {tab === "locations"  && <LocationsPane  {...common} data={data.locations}  usage={usage.locations || {}} bust={bust}/>}
        {tab === "music"      && <MusicPane      {...common} data={data.music}      usage={usage.background_audio || {}}/>}
        {tab === "sfx"        && <SfxPane        {...common} data={data.sfx}/>}
        {tab === "branding"   && <BrandingPane   {...common} clips={data.clips} files={data.files} usage={usage.branding_files || {}}/>}
      </div>
    </AsAudioProvider>
  );
}
