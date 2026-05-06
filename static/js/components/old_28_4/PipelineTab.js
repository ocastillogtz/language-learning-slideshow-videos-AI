const { useState, useEffect, useContext } = React;

function getInitialState(stepId, manifest) {
  const m = manifest || {};
  switch (stepId) {
    case 'script':
      return {
        char_a: (m.characters?.[0]?.name) || '',
        char_b: (m.characters?.[1]?.name) || '',
        location: m['location-key'] || '',
        style: m.style || 'shadowing',
        prompt: m['prompt-script'] || ''
      };
    case 'images': return { overwrite: false, ignore_cache: false };
    case 'video': return { overwrite: false, annotated: false };
    case 'assemble': return { branding: 'both', bg_audio: 'office', overwrite: false };
    case 'upload': return { privacy: 'private', title: '', desc: '' };
    default: return {};
  }
}

const STEP_CONFIGS = [
  {
    id: 'script', num: 1, title: 'Generate Script', desc: 'GPT writes dialogue, narration, and repetitions.',
    endpoint: n => `/projects/${n}/run/script`,
    renderFields: (form, setForm, manifest, characters, locations) => (
      <>
        <div className="field-row">
          <div className="field">
            <label>Character A</label>
            <select value={form.char_a} onChange={e => setForm(f => ({...f, char_a: e.target.value}))}>
              <option value="">Select…</option>
              {characters.map(c => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Character B</label>
            <select value={form.char_b} onChange={e => setForm(f => ({...f, char_b: e.target.value}))}>
              <option value="">Select…</option>
              {characters.map(c => <option key={c}>{c}</option>)}
            </select>
          </div>
        </div>
        <div className="field">
          <label>Location</label>
          <select value={form.location} onChange={e => setForm(f => ({...f, location: e.target.value}))}>
            <option value="">Select…</option>
            {locations.map(l => <option key={l}>{l}</option>)}
          </select>
        </div>
        <div className="field">
          <label>Style</label>
          <select value={form.style} onChange={e => setForm(f => ({...f, style: e.target.value}))}>
            <option value="shadowing">Shadowing (with repetitions)</option>
            <option value="story">Story (no repetitions)</option>
          </select>
        </div>
        <div className="prompt-section">
          <div className="prompt-header">
            <span>GPT Prompt (editable)</span>
            <button className="btn-ghost" type="button" onClick={async () => {
              if (!form.char_a || !form.char_b || !form.location) return;
              const res = await apiPost(`/projects/${manifest?.project?.name}/prompt/script`, {
                char_a: form.char_a, char_b: form.char_b, location: form.location, style: form.style
              });
              setForm(f => ({...f, prompt: res.prompt}));
            }}>⟳ Load Prompt</button>
          </div>
          <textarea className="prompt-editor" rows="6" value={form.prompt} onChange={e => setForm(f => ({...f, prompt: e.target.value}))} placeholder="Click 'Load Prompt' to preview..." />
        </div>
      </>
    ),
    buildPayload: (form) => ({
      char_a: form.char_a, char_b: form.char_b, location: form.location,
      style: form.style, prompt_override: form.prompt.trim() || null
    })
  },
  {
    id: 'audio', num: 2, title: 'Generate Audio', desc: 'ElevenLabs TTS for narration, dialogue, and repetitions.',
    endpoint: n => `/projects/${n}/run/audio`,
    renderFields: () => <div style={{color:'var(--muted)', fontSize:'.84rem', padding:'.4rem 0'}}>No parameters needed.</div>,
    buildPayload: () => ({})
  },
  {
    id: 'images', num: 3, title: 'Generate Images', desc: 'fal.ai generates scene images for every dialogue line.',
    endpoint: n => `/projects/${n}/run/images`,
    renderFields: (form, setForm) => (
      <>
        <div className="toggle-row">
          <input type="checkbox" id="f_ow_img" checked={form.overwrite} onChange={e => setForm(f => ({...f, overwrite: e.target.checked}))} />
          <label htmlFor="f_ow_img">Overwrite existing images</label>
        </div>
        <div className="toggle-row">
          <input type="checkbox" id="f_ic" checked={form.ignore_cache} onChange={e => setForm(f => ({...f, ignore_cache: e.target.checked}))} />
          <label htmlFor="f_ic">Ignore shared cache (always call fal.ai)</label>
        </div>
      </>
    ),
    buildPayload: (form) => ({ overwrite: form.overwrite, ignore_cache: form.ignore_cache })
  },
  {
    id: 'video', num: 4, title: 'Render Scene Clips', desc: 'MoviePy renders one .mp4 per scene.',
    endpoint: n => `/projects/${n}/run/video`,
    renderFields: (form, setForm) => (
      <>
        <div className="toggle-row">
          <input type="checkbox" id="f_ow_vid" checked={form.overwrite} onChange={e => setForm(f => ({...f, overwrite: e.target.checked}))} />
          <label htmlFor="f_ow_vid">Overwrite existing clips</label>
        </div>
        <div className="toggle-row">
          <input type="checkbox" id="f_ann" checked={form.annotated} onChange={e => setForm(f => ({...f, annotated: e.target.checked}))} />
          <label htmlFor="f_ann">Grammar-annotated subtitles</label>
        </div>
      </>
    ),
    buildPayload: (form) => ({ overwrite: form.overwrite, annotated_subtitles: form.annotated })
  },
  {
    id: 'assemble', num: 5, title: 'Assemble Final Video', desc: 'Concatenates clips, adds background music and branding.',
    endpoint: n => `/projects/${n}/run/assemble`,
    renderFields: (form, setForm) => (
      <>
        <div className="field-row">
          <div className="field">
            <label>Branding</label>
            <select value={form.branding} onChange={e => setForm(f => ({...f, branding: e.target.value}))}>
              <option value="both">Both (intro+outro)</option>
              <option value="intro">Intro only</option>
              <option value="outro">Outro only</option>
              <option value="none">None</option>
            </select>
          </div>
          <div className="field">
            <label>Background Audio</label>
            <input type="text" value={form.bg_audio} onChange={e => setForm(f => ({...f, bg_audio: e.target.value}))} placeholder="e.g. office, livingroom" />
          </div>
        </div>
        <div className="toggle-row">
          <input type="checkbox" id="f_ow_asm" checked={form.overwrite} onChange={e => setForm(f => ({...f, overwrite: e.target.checked}))} />
          <label htmlFor="f_ow_asm">Overwrite existing final video</label>
        </div>
      </>
    ),
    buildPayload: (form) => ({ branding: form.branding, bg_audio_name: form.bg_audio, overwrite: form.overwrite })
  },
  {
    id: 'upload', num: 6, title: 'Upload to YouTube', desc: 'Metadata auto-read from manifest.',
    endpoint: n => `/projects/${n}/run/upload`,
    renderFields: (form, setForm) => (
      <>
        <div className="field">
          <label>Privacy</label>
          <select value={form.privacy} onChange={e => setForm(f => ({...f, privacy: e.target.value}))}>
            <option value="private">Private</option>
            <option value="unlisted">Unlisted</option>
            <option value="public">Public</option>
          </select>
        </div>
        <div className="field">
          <label>Title Override <span style={{color:'var(--muted)', fontWeight:300}}>(optional)</span></label>
          <input type="text" value={form.title} onChange={e => setForm(f => ({...f, title: e.target.value}))} placeholder="Leave blank to use manifest title" />
        </div>
        <div className="field">
          <label>Description Override <span style={{color:'var(--muted)', fontWeight:300}}>(optional)</span></label>
          <textarea rows="3" value={form.desc} onChange={e => setForm(f => ({...f, desc: e.target.value}))} placeholder="Leave blank to auto-generate" />
        </div>
      </>
    ),
    buildPayload: (form) => ({ privacy: form.privacy, title: form.title, description: form.desc })
  }
];

function StepCard({ config, project, manifest, characters, locations }) {
  const [isOpen, setIsOpen] = useState(false);
  const [form, setForm] = useState(() => getInitialState(config.id, manifest));
  const { status, log, start } = useJob(project, config.id);
  const { addToast, loadManifest, refreshProjects } = useContext(AppContext);

  useEffect(() => {
    setForm(getInitialState(config.id, manifest));
  }, [manifest, config.id]);

  useEffect(() => {
    if (status === 'done') {
      addToast('Done', `${config.title} finished.`, 'ok');
      loadManifest(project);
      refreshProjects();
    } else if (status === 'error') {
      addToast('Error', `${config.title} failed: ${log}`, 'err');
    }
  }, [status, log]);

  async function handleRun() {
    try {
      const payload = config.buildPayload(form);
      await apiPost(config.endpoint(project), payload);
      start();
    } catch (e) {
      addToast('Error', e.message, 'err');
    }
  }

  return (
    <div className={`step-card ${isOpen ? 'open' : ''}`}>
      <div className="step-head" onClick={() => setIsOpen(!isOpen)}>
        <div className="step-num">{config.num}</div>
        <div style={{ flex: 1 }}>
          <div className="step-title">{config.title}</div>
          <div className="step-desc">{config.desc}</div>
        </div>
        <div className={`badge badge-${status}`}>{status}</div>
        <div className="chevron">▼</div>
      </div>
      <div className="step-body">
        <div className="fields">
          {config.renderFields(form, setForm, manifest, characters, locations)}
        </div>
        <div className="run-row">
          <button className="btn-primary" onClick={handleRun} disabled={status === 'running'}>
            <svg width="11" height="11" viewBox="0 0 11 11" fill="currentColor"><polygon points="1,0.5 10.5,5.5 1,10.5"/></svg>
            Run
            {status === 'running' && <div className="spin" style={{ display: 'inline-block', marginLeft: 8 }} />}
          </button>
        </div>
        {log && <div className={`step-log vis${status === 'error' ? ' err' : ''}`}>{log}</div>}
      </div>
    </div>
  );
}

function PipelineTab() {
  const { currentProject, manifest, characters, locations } = useContext(AppContext);
  if (!currentProject) return null;

  return (
    <div className="pipeline">
      {STEP_CONFIGS.map(cfg => (
        <StepCard
          key={cfg.id}
          config={cfg}
          project={currentProject}
          manifest={manifest}
          characters={characters}
          locations={locations}
        />
      ))}
    </div>
  );
}
