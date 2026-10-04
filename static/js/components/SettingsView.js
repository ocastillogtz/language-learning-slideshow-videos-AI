// SettingsView.js — top-level "Settings" page.
// Everything a workspace (one language / channel) can be tuned with: the workspace
// itself (language, channel, icon, mascot), art-style prompts, on-screen labels,
// channel/upload metadata, AI models, project-type prompts, subtitle styling,
// connections and — under "All settings" — every config.ini value.
//
// config.ini holds the defaults; edits are saved as overrides of the ACTIVE
// workspace (PUT /settings), so another workspace keeps its own values.
const { useState, useEffect, useMemo, useRef, useCallback } = React;

// ── Shared bits ───────────────────────────────────────────────────────────────

function Flag({ code, size }) {
  if (!code) return null;
  return <span className={`fi fi-${code} flag`} style={size ? {fontSize:size} : null}/>;
}

function LanguageSelect({ value, onChange, languages }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const close = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  const cur = languages.find(l => l.code === value);
  return (
    <div className="lang-select" ref={ref}>
      <button type="button" className="lang-btn" onClick={() => setOpen(o => !o)}>
        {cur ? <><Flag code={cur.flag}/><span>{cur.name}</span><span className="lang-native">{cur.native}</span></>
             : <span className="lang-native">Choose a language…</span>}
        <span className="lang-caret">▾</span>
      </button>
      {open && (
        <div className="lang-menu">
          {languages.map(l => (
            <div key={l.code} className={"lang-opt" + (l.code === value ? " sel" : "")}
              onClick={() => { onChange(l.code); setOpen(false); }}>
              <Flag code={l.flag}/><span>{l.name}</span><span className="lang-native">{l.native}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StImageSlot({ label, url, hint, onUpload }) {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  async function pick(e) {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    setBusy(true);
    try { await onUpload(f); } finally { setBusy(false); }
  }
  return (
    <div className="img-slot" onClick={() => inputRef.current.click()} title={`Upload ${label.toLowerCase()}`}>
      <div className="img-slot-pic">
        {url ? <img src={url} alt={label}/> : <span>+</span>}
      </div>
      <div className="img-slot-txt">
        <strong>{label}</strong>
        <span>{busy ? "Uploading…" : (url ? "Click to replace" : hint)}</span>
      </div>
      <input ref={inputRef} type="file" accept="image/*" style={{display:"none"}} onChange={pick}/>
    </div>
  );
}

function prettyKey(k) {
  return k.replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
}

// ── Settings data (all config.ini values + overrides) ─────────────────────────

function useSettingsData() {
  const { toast } = useApp();
  const [sections, setSections] = useState([]);
  const [edits,    setEdits]    = useState({});      // "section.key" -> new value (or null = reset)
  const [saving,   setSaving]   = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await apiGet("/settings");
      setSections(d.sections || []);
      setEdits({});
    } catch (e) { toast("Error", e.message, "err"); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const index = useMemo(() => {
    const m = {};
    sections.forEach(s => s.keys.forEach(k => { m[`${s.name}.${k.key}`] = { ...k, section: s.name }; }));
    return m;
  }, [sections]);

  function valueOf(id) {
    if (id in edits) return edits[id] === null ? (index[id]?.default ?? "") : edits[id];
    return index[id]?.value ?? "";
  }
  function setValue(id, v) { setEdits(p => ({ ...p, [id]: v })); }
  function reset(id)       { setEdits(p => ({ ...p, [id]: null })); }

  async function save() {
    const updates = {};
    Object.entries(edits).forEach(([id, v]) => {
      const [sec, ...rest] = id.split(".");
      (updates[sec] = updates[sec] || {})[rest.join(".")] = v;
    });
    setSaving(true);
    try {
      await apiPut("/settings", { updates });
      toast("Saved", "Settings updated for this workspace.", "ok");
      await load();
    } catch (e) { toast("Error", e.message, "err"); }
    setSaving(false);
  }

  return { sections, index, edits, valueOf, setValue, reset, save, discard: () => setEdits({}),
           dirty: Object.keys(edits).length, saving };
}

function SettingField({ id, label, data, multiline, mono }) {
  const item = data.index[id];
  if (!item) return null;
  const value = data.valueOf(id);
  const edited = id in data.edits;
  const overridden = edited ? (data.edits[id] !== null && data.edits[id] !== item.default) : item.overridden;
  // Decide input vs textarea from the SAVED value, not the live one — switching the
  // element type while typing would remount it and drop the focus.
  const long = multiline || String(item.value || "").length > 70 || String(item.default || "").length > 70;
  return (
    <div className={"set-field" + (edited ? " edited" : "")}>
      <div className="set-field-hdr">
        <label>{label || prettyKey(item.key)}</label>
        <code className="set-key">[{item.section}] {item.key}</code>
        {overridden && (
          <button className="set-reset" title={`Default: ${item.default || "(empty)"}`}
            onClick={() => data.reset(id)}>
            Customised · reset
          </button>
        )}
      </div>
      {long
        ? <textarea className={mono ? "mono" : ""} rows={Math.min(12, Math.max(3, Math.ceil(String(value).length / 95)))}
            value={value} onChange={e => data.setValue(id, e.target.value)}/>
        : <input value={value} onChange={e => data.setValue(id, e.target.value)}/>}
      {item.help && <div className="set-help">{item.help}</div>}
    </div>
  );
}

function SaveBar({ data }) {
  if (!data.dirty) return null;
  return (
    <div className="save-bar">
      <span>{data.dirty} unsaved change{data.dirty === 1 ? "" : "s"}</span>
      <button className="btn-cancel" onClick={data.discard}>Discard</button>
      <button className="btn-primary" disabled={data.saving} onClick={data.save}>
        {data.saving ? "Saving…" : "Save changes"}
      </button>
    </div>
  );
}

function CuratedGroup({ title, intro, fields, data }) {
  return (
    <div className="set-card">
      <h3>{title}</h3>
      {intro && <p className="set-intro">{intro}</p>}
      {fields.map(f => <SettingField key={f.id} {...f} data={data}/>)}
    </div>
  );
}

// ── Workspace tab ─────────────────────────────────────────────────────────────

function WorkspaceTab() {
  const { toast, workspace, workspaces, languages, loadWorkspaces, switchWorkspace } = useApp();
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [nw, setNw] = useState({ name: "", language_code: "", channel_name: "",
                                 clone_from: "", copy: { settings: true, characters: false, locations: false } });
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (workspace) setForm({ name: workspace.name, language_code: workspace.language_code,
                             channel_name: workspace.channel_name || "" });
  }, [workspace && workspace.slug, workspace && workspace.updated_at]);
  useEffect(() => { if (workspace && !nw.clone_from) setNw(p => ({ ...p, clone_from: workspace.slug })); }, [workspace]);

  if (!workspace || !form) return <div className="set-card">Loading…</div>;

  const dirty = form.name !== workspace.name || form.language_code !== workspace.language_code
             || form.channel_name !== (workspace.channel_name || "");

  async function saveWs() {
    setSaving(true);
    try {
      await apiPut(`/workspaces/${workspace.slug}`, form);
      await loadWorkspaces();
      toast("Saved", "Workspace updated.", "ok");
    } catch (e) { toast("Error", e.message, "err"); }
    setSaving(false);
  }
  async function upload(kind, file) {
    const fd = new FormData();
    fd.append("file", file);
    try {
      await apiPostForm(`/workspaces/${workspace.slug}/image/${kind}`, fd);
      await loadWorkspaces();
      toast("Uploaded", `${prettyKey(kind)} updated.`, "ok");
    } catch (e) { toast("Error", e.message, "err"); }
  }
  async function create() {
    setCreating(true);
    try {
      const d = await apiPost("/workspaces", {
        name: nw.name, language_code: nw.language_code, channel_name: nw.channel_name,
        clone_from: nw.clone_from, copy: Object.keys(nw.copy).filter(k => nw.copy[k]),
      });
      toast("Created", `Workspace “${d.workspace.name}” is ready.`, "ok");
      setNw(p => ({ ...p, name: "", language_code: "", channel_name: "" }));
      await loadWorkspaces();
      if (confirm(`Switch to “${d.workspace.name}” now?`)) await switchWorkspace(d.workspace.slug);
    } catch (e) { toast("Error", e.message, "err"); }
    setCreating(false);
  }
  async function remove(w) {
    if (!confirm(`Remove workspace “${w.name}”?\n\nIts settings and catalog are forgotten; its folders stay on disk:\n${w.assets_dir}\n${w.projects_dir}`)) return;
    try { await apiDelete(`/workspaces/${w.slug}`); await loadWorkspaces(); toast("Removed", w.name, "ok"); }
    catch (e) { toast("Error", e.message, "err"); }
  }

  return (
    <>
      <div className="set-card">
        <h3>This workspace</h3>
        <p className="set-intro">
          A workspace is one language / channel. Its characters, locations, project types, settings
          and projects are its own; background music and SFX are shared by all workspaces.
        </p>
        <div className="ws-brand">
          <StImageSlot label="Icon" url={workspace.icon_url} hint="Square logo for the header"
            onUpload={f => upload("icon", f)}/>
          <StImageSlot label="Mascot" url={workspace.mascot_url} hint="Channel mascot artwork"
            onUpload={f => upload("mascot", f)}/>
        </div>
        <div className="field-row" style={{marginTop:"1rem"}}>
          <div className="field"><label>Workspace name</label>
            <input value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))}/></div>
          <div className="field"><label>Channel name</label>
            <input value={form.channel_name} placeholder="e.g. Brezel"
              onChange={e => setForm(p => ({ ...p, channel_name: e.target.value }))}/></div>
        </div>
        <div className="field" style={{marginTop:".8rem"}}><label>Language being taught</label>
          <LanguageSelect value={form.language_code} languages={languages}
            onChange={v => setForm(p => ({ ...p, language_code: v }))}/>
          <div className="set-help">
            Script, review and lyric-transcription prompts use this language ({"{LANGUAGE}"} in project-type prompts).
          </div>
        </div>
        <div className="set-meta">
          <span>Assets: <code>{workspace.assets_dir}</code></span>
          <span>Projects: <code>{workspace.projects_dir}</code></span>
        </div>
        {dirty && (
          <div className="edit-actions">
            <button className="btn-primary" disabled={saving} onClick={saveWs}>{saving ? "Saving…" : "Save workspace"}</button>
            <button className="btn-cancel" onClick={() => setForm({ name: workspace.name, language_code: workspace.language_code, channel_name: workspace.channel_name || "" })}>Discard</button>
          </div>
        )}
      </div>

      <div className="set-card">
        <h3>All workspaces</h3>
        <div className="ws-list">
          {workspaces.map(w => (
            <div key={w.slug} className={"ws-row" + (w.slug === workspace.slug ? " active" : "")}>
              <div className="ws-avatar">{w.icon_url ? <img src={w.icon_url} alt=""/> : <Flag code={w.language.flag}/>}</div>
              <div className="ws-row-main">
                <div className="ws-row-name"><Flag code={w.language.flag}/> {w.name}</div>
                <div className="ws-row-sub">{w.language.name}{w.channel_name ? ` · ${w.channel_name}` : ""} · {w.projects_dir}</div>
              </div>
              {w.slug === workspace.slug
                ? <span className="badge badge-done">Active</span>
                : <>
                    <button className="btn-ghost" onClick={() => switchWorkspace(w.slug)}>Switch</button>
                    <button className="btn-edit" onClick={() => remove(w)}>Remove</button>
                  </>}
            </div>
          ))}
        </div>
      </div>

      <div className="set-card">
        <h3>New workspace</h3>
        <p className="set-intro">Start a pipeline for another language or channel. Project types are always copied so you can make videos right away — review their prompts under <em>Project types</em>, since their examples are written for the source language.</p>
        <div className="field-row">
          <div className="field"><label>Name</label>
            <input value={nw.name} placeholder="e.g. Spanish" onChange={e => setNw(p => ({ ...p, name: e.target.value }))}/></div>
          <div className="field"><label>Channel name</label>
            <input value={nw.channel_name} onChange={e => setNw(p => ({ ...p, channel_name: e.target.value }))}/></div>
        </div>
        <div className="field" style={{marginTop:".8rem"}}><label>Language</label>
          <LanguageSelect value={nw.language_code} languages={languages}
            onChange={v => setNw(p => ({ ...p, language_code: v }))}/></div>
        <div className="field" style={{marginTop:".8rem"}}><label>Copy from</label>
          <select value={nw.clone_from} onChange={e => setNw(p => ({ ...p, clone_from: e.target.value }))}>
            {workspaces.map(w => <option key={w.slug} value={w.slug}>{w.name}</option>)}
          </select>
        </div>
        <div className="ws-copy">
          {[["settings", "Settings (art style, labels, subtitle styling…)"],
            ["characters", "Characters (with their art)"],
            ["locations", "Locations (with their art)"]].map(([k, label]) => (
            <label key={k} className="toggle-row">
              <input type="checkbox" checked={nw.copy[k]}
                onChange={e => setNw(p => ({ ...p, copy: { ...p.copy, [k]: e.target.checked } }))}/>
              {label}
            </label>
          ))}
        </div>
        <div className="edit-actions">
          <button className="btn-primary" disabled={creating || !nw.name.trim() || !nw.language_code} onClick={create}>
            {creating ? "Creating…" : "Create workspace"}
          </button>
        </div>
      </div>
    </>
  );
}

// ── Project types tab ─────────────────────────────────────────────────────────

const PROMPT_PLACEHOLDERS = [
  ["{LANGUAGE}", "language being taught"], ["{LANGUAGE_NATIVE}", "its own name"],
  ["{LEVEL}", "CEFR level"], ["{LEVEL_LOWER}", "level, lowercase"], ["{CHANNEL}", "channel name"],
  ["{HASHTAGS}", "channel hashtags"], ["{CHAR_A}", ""], ["{CHAR_B}", ""], ["{CHAR_A_DESC}", ""],
  ["{CHAR_B_DESC}", ""], ["{LOCATION_KEY}", ""], ["{LOCATION_DESC}", ""], ["{WORDS_LIST}", ""],
  ["{DIALOG_COUNT}", ""], ["{PROVIDED_CONTEXT}", "scene description"],
  ["{PROVIDED_LEARNING_POINTS}", "learning points"],
];

function ProjectTypesTab() {
  const { toast } = useApp();
  const [types, setTypes]     = useState({});
  const [shipped, setShipped] = useState([]);
  const [sel, setSel]         = useState(null);
  const [draft, setDraft]     = useState(null);   // {self_description, prompt, rest(json text)}
  const [filter, setFilter]   = useState("");
  const [saving, setSaving]   = useState(false);
  const promptRef = useRef(null);

  const load = useCallback(async (keep) => {
    try {
      const d = await apiGet("/settings/project-types");
      setTypes(d.types || {}); setShipped(d.shipped || []);
      const first = keep && d.types[keep] ? keep : Object.keys(d.types || {})[0];
      if (first) choose(first, d.types);
    } catch (e) { toast("Error", e.message, "err"); }
  }, []);
  useEffect(() => { load(); }, [load]);

  function choose(key, src) {
    const t = (src || types)[key];
    if (!t) return;
    const { self_description, description_for_prompt, ...rest } = t;
    setSel(key);
    setDraft({ self_description: self_description || "", prompt: description_for_prompt || "",
               rest: JSON.stringify(rest, null, 2), dirty: false });
  }
  function upd(k, v) { setDraft(p => ({ ...p, [k]: v, dirty: true })); }

  function insert(ph) {
    const ta = promptRef.current;
    if (!ta) return;
    const s = ta.selectionStart, e = ta.selectionEnd;
    upd("prompt", draft.prompt.slice(0, s) + ph + draft.prompt.slice(e));
    setTimeout(() => { ta.focus(); ta.selectionStart = ta.selectionEnd = s + ph.length; }, 0);
  }

  async function save() {
    let rest;
    try { rest = JSON.parse(draft.rest); }
    catch (e) { toast("Invalid JSON", "Advanced settings: " + e.message, "err"); return; }
    setSaving(true);
    try {
      await apiPut(`/settings/project-types/${sel}`,
        { ...rest, self_description: draft.self_description, description_for_prompt: draft.prompt });
      toast("Saved", `Project type “${sel}” updated.`, "ok");
      await load(sel);
    } catch (e) { toast("Error", e.message, "err"); }
    setSaving(false);
  }
  async function duplicate() {
    const nk = prompt(`Duplicate “${sel}” as (new key):`, `${sel}_copy`);
    if (!nk) return;
    try { const d = await apiPost(`/settings/project-types/${sel}/duplicate`, { new_key: nk }); await load(d.key); }
    catch (e) { toast("Error", e.message, "err"); }
  }
  async function resetShipped() {
    if (!confirm(`Restore the shipped prompt for “${sel}”? Your edits to it are lost.`)) return;
    try { await apiPost(`/settings/project-types/reset/${sel}`, {}); await load(sel); toast("Restored", sel, "ok"); }
    catch (e) { toast("Error", e.message, "err"); }
  }
  async function remove() {
    if (!confirm(`Delete project type “${sel}” from this workspace?`)) return;
    try { await apiDelete(`/settings/project-types/${sel}`); await load(); }
    catch (e) { toast("Error", e.message, "err"); }
  }

  const keys = Object.keys(types).filter(k => !filter || k.includes(filter.toLowerCase())
    || (types[k].self_description || "").toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="pt-wrap">
      <div className="pt-list">
        <input className="pt-filter" placeholder="Filter types…" value={filter} onChange={e => setFilter(e.target.value)}/>
        {keys.map(k => (
          <div key={k} className={"pt-item" + (k === sel ? " active" : "")} onClick={() => choose(k)}>
            <div className="pt-key">{k}</div>
            <div className="pt-desc">{(types[k].self_description || "").slice(0, 70)}</div>
          </div>
        ))}
      </div>
      {draft && (
        <div className="set-card pt-editor">
          <div className="pt-head">
            <h3>{sel}</h3>
            {types[sel]?.base_type && <span className="tag">inherits prompt from {types[sel].base_type}</span>}
            <div style={{marginLeft:"auto",display:"flex",gap:".4rem"}}>
              <button className="btn-edit" onClick={duplicate}>Duplicate</button>
              {shipped.includes(sel) && <button className="btn-edit" onClick={resetShipped}>Reset to shipped</button>}
              <button className="btn-edit" onClick={remove}>Delete</button>
            </div>
          </div>
          <div className="field"><label>What it makes (shown when picking a type)</label>
            <textarea rows={3} value={draft.self_description} onChange={e => upd("self_description", e.target.value)}/></div>
          <div className="field" style={{marginTop:".9rem"}}><label>Script prompt</label>
            <div className="ph-chips">
              {PROMPT_PLACEHOLDERS.map(([ph, tip]) => (
                <button key={ph} className="ph-chip" title={tip || ph} onClick={() => insert(ph)}>{ph}</button>
              ))}
            </div>
            <textarea ref={promptRef} className="prompt-editor" rows={22} value={draft.prompt}
              placeholder={types[sel]?.base_type ? `Empty: uses the prompt of “${types[sel].base_type}”.` : ""}
              onChange={e => upd("prompt", e.target.value)}/>
            <div className="set-help">Placeholders in {"{BRACES}"} are filled in when a script is generated. Write literal braces (e.g. in JSON examples) doubled: {"{{ }}"}.</div>
          </div>
          <details className="pt-adv">
            <summary>Advanced — output schema, scene rules, defaults (JSON)</summary>
            <textarea className="prompt-editor" rows={16} value={draft.rest} onChange={e => upd("rest", e.target.value)}/>
          </details>
          {draft.dirty && (
            <div className="edit-actions">
              <button className="btn-primary" disabled={saving} onClick={save}>{saving ? "Saving…" : "Save project type"}</button>
              <button className="btn-cancel" onClick={() => choose(sel)}>Discard</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── All settings (every config.ini section) ───────────────────────────────────

function AllSettingsTab({ data }) {
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  return (
    <>
      <input className="pt-filter" style={{marginBottom:"1rem"}} placeholder="Search all settings…"
        value={q} onChange={e => setQ(e.target.value)}/>
      {data.sections.map(sec => {
        const keys = sec.keys.filter(k => !needle || `${sec.name} ${k.key} ${k.help}`.toLowerCase().includes(needle));
        if (!keys.length) return null;
        return (
          <div key={sec.name} className="set-card">
            <h3>[{sec.name}]</h3>
            {sec.help && <p className="set-intro">{sec.help}</p>}
            {keys.map(k => <SettingField key={k.key} id={`${sec.name}.${k.key}`} data={data}/>)}
          </div>
        );
      })}
    </>
  );
}

// ── The page ──────────────────────────────────────────────────────────────────

const SETTINGS_TABS = [
  { id: "workspace",   label: "Workspace",            hint: "Language, channel, icon & mascot" },
  { id: "art",         label: "Art style",            hint: "Image style prompts" },
  { id: "text",        label: "On-screen text",       hint: "Labels to translate" },
  { id: "channel",     label: "Channel & uploads",    hint: "Titles, hashtags, tags" },
  { id: "ai",          label: "Script & AI models",   hint: "Level, GPT, image, voice" },
  { id: "types",       label: "Project types",        hint: "Script prompts per video type" },
  { id: "subtitles",   label: "Subtitles & overlays", hint: "Fonts, colours, live preview" },
  { id: "connections", label: "Connections",          hint: "YouTube, Instagram, Facebook" },
  { id: "all",         label: "All settings",         hint: "Every config value" },
];

function SettingsView({ tab, onTab }) {
  const { workspace } = useApp();
  const data = useSettingsData();

  const groups = {
    art: [{
      title: "Art style",
      intro: "These prompts define the look of every generated image. Change them to give a workspace its own visual style.",
      fields: [
        { id: "image_prompts.style_tokens",        label: "Scene art style",        multiline: true },
        { id: "image_prompts.framing_tokens",      label: "Framing / composition",  multiline: true },
        { id: "image_prompts.character_art_style", label: "Character art style",    multiline: true },
        { id: "image_prompts.location_art_style",  label: "Location art style",     multiline: true },
      ],
    }],
    text: [{
      title: "On-screen text",
      intro: "Words burned into the videos. Translate them when you start a workspace for a new language.",
      fields: [
        { id: "repeat_prompt.text",          label: "Shadowing “repeat now” cue" },
        { id: "reading.part_label_word",     label: "Part label (before the part number)" },
        { id: "reading.continuation_text",   label: "“To be continued” end card" },
        { id: "podcast.short_label",         label: "Podcast name on Shorts" },
        { id: "podcast.short_cta_text",      label: "Shorts call to action" },
        { id: "podcast.full_episode_label",  label: "Full-episode link label" },
        { id: "song.stt_language",           label: "Lyrics transcription language (ISO 639-3)" },
      ],
    }],
    channel: [{
      title: "Channel & uploads",
      intro: "Used in generated titles and descriptions and as default upload metadata.",
      fields: [
        { id: "channel.hashtags",            label: "Hashtags" },
        { id: "channel.title_suffix",        label: "Short title suffix" },
        { id: "channel.default_title",       label: "Fallback video title" },
        { id: "channel.default_description", label: "Description footer" },
        { id: "channel.tags",                label: "YouTube tags" },
        { id: "podcast.full_episode_url",    label: "Podcast full-episode URL" },
      ],
    }],
    ai: [{
      title: "Script & AI models",
      fields: [
        { id: "script.level",                label: "Default CEFR level" },
        { id: "script.openai_model",         label: "Script model (OpenAI)" },
        { id: "review.openai_model",         label: "Review model (OpenAI)" },
        { id: "script.max_scene_characters", label: "Max characters per image" },
        { id: "script.dialog_batch_size",    label: "Dialog batch size" },
        { id: "fal.model",                   label: "Image edit model (fal)" },
        { id: "fal.t2i_model",               label: "Text-to-image model (fal)" },
        { id: "audio.elevenlabs_model",      label: "Voice model (ElevenLabs)" },
      ],
    }],
  };

  const usesSettings = ["art", "text", "channel", "ai", "all"].includes(tab);

  return (
    <div className="set-shell">
      <nav className="set-nav">
        <div className="set-nav-ws">
          {workspace && <><Flag code={workspace.language.flag}/> <span>{workspace.name}</span></>}
        </div>
        {SETTINGS_TABS.map(t => (
          <button key={t.id} className={"set-nav-item" + (tab === t.id ? " active" : "")} onClick={() => onTab(t.id)}>
            <span>{t.label}</span>
            <small>{t.hint}</small>
          </button>
        ))}
      </nav>
      <div className="set-main">
        {tab === "workspace"   && <WorkspaceTab/>}
        {groups[tab] && groups[tab].map(g => <CuratedGroup key={g.title} {...g} data={data}/>)}
        {tab === "types"       && <ProjectTypesTab/>}
        {tab === "subtitles"   && <SubtitlesTab/>}
        {tab === "connections" && <ConnectionsTab/>}
        {tab === "all"         && <AllSettingsTab data={data}/>}
        {usesSettings && <SaveBar data={data}/>}
      </div>
    </div>
  );
}
