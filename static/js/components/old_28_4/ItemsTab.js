const { useState, useEffect, useContext } = React;

function SampleZone({ itemType, index, samplePath, project }) {
  const slot = itemType === 'narration' ? 'narration' : `dialog_${index}`;
  const [uploading, setUploading] = useState(false);
  const { addToast, loadManifest } = useContext(AppContext);

  async function upload(file) {
    if (!file) return;
    setUploading(true);
    const fd = new FormData();
    fd.append('file', file);
    fd.append('slot', slot);
    try {
      await fetch(`/projects/${project}/upload/sample_image`, { method: 'POST', body: fd });
      addToast('Saved', 'Reference image uploaded.', 'ok');
      await loadManifest(project);
    } catch (e) {
      addToast('Error', e.message, 'err');
    } finally {
      setUploading(false);
    }
  }

  async function remove() {
    try {
      await apiDelete(`/projects/${project}/upload/sample_image/${slot}`);
      addToast('Removed', 'Reference image cleared.', 'ok');
      await loadManifest(project);
    } catch (e) {
      addToast('Error', e.message, 'err');
    }
  }

  function handleDrop(e) {
    e.preventDefault();
    e.currentTarget.classList.remove('dragover');
    const file = e.dataTransfer?.files?.[0];
    if (file) upload(file);
  }

  const hasSample = !!samplePath;

  return (
    <div className="sample-zone">
      <div className="sample-label">
        <span>Reference Image for Generation</span>
        {hasSample && <button className="sample-remove" onClick={remove}>✕ Remove</button>}
      </div>
      {hasSample ? (
        <div className="sample-preview">
          <img className="sample-thumb" src={`/project-files/${project}/${samplePath}?t=${Date.now()}`} alt="sample" />
          <div className="sample-info">
            <strong>Custom reference active</strong>
            This image will be sent to fal.ai instead of the default composite when you re-generate.
          </div>
        </div>
      ) : (
        <div
          className="sample-drop"
          onDragOver={e => { e.preventDefault(); e.currentTarget.classList.add('dragover'); }}
          onDragLeave={e => e.currentTarget.classList.remove('dragover')}
          onDrop={handleDrop}
        >
          <input type="file" accept="image/png,image/jpeg,image/webp" onChange={e => upload(e.target.files[0])} style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%' }} />
          <div className="sample-drop-text">Drop an image or <strong>click to browse</strong><br /><span style={{ fontSize: '.72rem' }}>PNG · JPG · WEBP</span></div>
        </div>
      )}
      {uploading && <div className="sample-uploading">Uploading…</div>}
    </div>
  );
}

function NarrationCard({ narr, project }) {
  const [isOpen, setIsOpen] = useState(false);
  const [text, setText] = useState(narr.text || '');
  const [prompt, setPrompt] = useState(narr['prompt-image'] || '');
  const [saving, setSaving] = useState(false);
  const { addToast, loadManifest } = useContext(AppContext);
  const { status: regenStatus, start: startRegen } = useJob(project, 'image_narration_-1');

  useEffect(() => { setText(narr.text || ''); setPrompt(narr['prompt-image'] || ''); }, [narr.text, narr['prompt-image']]);

  async function save() {
    setSaving(true);
    try {
      await apiPost(`/projects/${project}/narration`, { text });
      addToast('Saved', 'Narration updated.', 'ok');
      await loadManifest(project);
    } catch (e) {
      addToast('Error', e.message, 'err');
    } finally {
      setSaving(false);
    }
  }

  async function regen() {
    try {
      await apiPost(`/projects/${project}/run/image_single`, {
        item_type: 'narration', dialog_index: -1, prompt_override: prompt.trim() || null
      });
      startRegen();
    } catch (e) {
      addToast('Error', e.message, 'err');
    }
  }

  const hasImg = !!narr.image;
  const hasAudio = !!narr['audio-file'];

  return (
    <div className={`item-card ${isOpen ? 'open' : ''}`}>
      <div className="item-head" onClick={() => setIsOpen(!isOpen)}>
        <div className="item-index">NAR</div>
        <div className="item-text">{narr.text || '—'}</div>
        <span className={`item-status-badge ${hasImg ? 'badge-done' : 'badge-idle'}`}>{hasImg ? 'img ✓' : 'no img'}</span>
        <span className={`item-status-badge ${hasAudio ? 'badge-done' : 'badge-idle'}`} style={{marginLeft:'.3rem'}}>{hasAudio ? 'audio ✓' : 'no audio'}</span>
        <div className="chevron" style={{marginLeft:'.5rem'}}>▼</div>
      </div>
      <div className="item-body">
        <div style={{ display: 'flex', gap: '1.2rem', marginTop: '1rem', flexWrap: 'wrap', alignItems: 'flex-start' }}>
          {hasImg ? (
            <div><img className="item-image" src={`/project-files/${project}/${narr.image}?t=${Date.now()}`} alt="narration" /></div>
          ) : (
            <div className="item-no-image">No image yet.</div>
          )}
          {hasAudio && (
            <div style={{ marginTop: '.1rem' }}>
              <div className="mf-label" style={{ marginBottom: '.35rem' }}>Audio</div>
              <audio controls src={`/project-files/${project}/${narr['audio-file']}`} style={{ height: 36, width: 220 }} />
            </div>
          )}
        </div>
        <SampleZone itemType="narration" index={-1} samplePath={narr['sample-image']} project={project} />
        <div className="fields" style={{ marginTop: '.9rem' }}>
          <div className="field"><label>Narration Text</label><textarea rows="2" value={text} onChange={e => setText(e.target.value)} /></div>
        </div>
        <div className="run-row" style={{ marginTop: '.6rem' }}>
          <button className="btn-primary" onClick={save} disabled={saving} style={{ fontSize: '.8rem', padding: '.45rem 1rem' }}>
            {saving ? 'Saving…' : 'Save Text'}
          </button>
        </div>
        <div className="prompt-section">
          <div className="prompt-header"><span>Image Prompt</span></div>
          <textarea className="prompt-editor" rows="4" value={prompt} onChange={e => setPrompt(e.target.value)} />
        </div>
        <div className="run-row">
          <button className="btn-primary" onClick={regen} disabled={regenStatus === 'running'} style={{ fontSize: '.8rem', padding: '.45rem 1rem' }}>
            ⟳ Re-generate Image
            {regenStatus === 'running' && <div className="spin" style={{ display: 'inline-block', marginLeft: 8 }} />}
          </button>
        </div>
        {regenStatus === 'error' && <div className="step-log vis err">Image generation failed.</div>}
      </div>
    </div>
  );
}

function DialogCard({ item, index, project }) {
  const [isOpen, setIsOpen] = useState(false);
  const [text, setText] = useState(item.text || '');
  const [posture, setPosture] = useState(item['speaker-posture'] || '');
  const [cutaway, setCutaway] = useState(item.cutaway || '');
  const [prompt, setPrompt] = useState(item['prompt-image'] || item['prompt-cutaway-image'] || '');
  const [saving, setSaving] = useState(false);
  const { addToast, loadManifest } = useContext(AppContext);
  const { status: regenStatus, start: startRegen } = useJob(project, `image_dialog_${index}`);

  useEffect(() => {
    setText(item.text || '');
    setPosture(item['speaker-posture'] || '');
    setCutaway(item.cutaway || '');
    setPrompt(item['prompt-image'] || item['prompt-cutaway-image'] || '');
  }, [item]);

  async function save() {
    setSaving(true);
    try {
      const body = { text };
      if (posture) body.speaker_posture = posture;
      if (item.cutaway !== undefined || cutaway) body.cutaway = cutaway;
      await apiPost(`/projects/${project}/dialog/${index}`, body);
      addToast('Saved', 'Dialog updated.', 'ok');
      await loadManifest(project);
    } catch (e) {
      addToast('Error', e.message, 'err');
    } finally {
      setSaving(false);
    }
  }

  async function regen() {
    try {
      await apiPost(`/projects/${project}/run/image_single`, {
        item_type: 'dialog', dialog_index: index, prompt_override: prompt.trim() || null
      });
      startRegen();
    } catch (e) {
      addToast('Error', e.message, 'err');
    }
  }

  const hasImg = !!item.image;
  const hasAudio = !!item['audio-file'];
  const isCutaway = !!item.cutaway;

  return (
    <div className={`item-card ${isOpen ? 'open' : ''}`}>
      <div className="item-head" onClick={() => setIsOpen(!isOpen)}>
        <div className="item-index">{index}</div>
        <div className="item-speaker">{item.speaker}</div>
        <div className="item-text">{item.text}</div>
        {isCutaway && <span style={{ fontSize: '.68rem', color: 'var(--orange)', margin: '0 .3rem' }}>✂ cutaway</span>}
        <div className="item-shot">{item.shot_type || ''}</div>
        <span className={`item-status-badge ${hasImg ? 'badge-done' : 'badge-idle'}`} style={{ marginLeft: '.5rem' }}>{hasImg ? 'img ✓' : 'no img'}</span>
        <span className={`item-status-badge ${hasAudio ? 'badge-done' : 'badge-idle'}`} style={{ marginLeft: '.3rem' }}>{hasAudio ? 'audio ✓' : 'no audio'}</span>
        <div className="chevron" style={{ marginLeft: '.5rem' }}>▼</div>
      </div>
      <div className="item-body">
        {item['speaker-posture'] && <div style={{ fontSize: '.8rem', color: 'var(--muted)', marginTop: '.8rem', fontStyle: 'italic' }}>Posture: {item['speaker-posture']}</div>}
        {isCutaway && <div style={{ fontSize: '.8rem', color: 'var(--orange)', marginTop: '.5rem' }}>Cutaway: {item.cutaway}</div>}
        <div className="fields" style={{ marginTop: '.9rem' }}>
          <div className="field"><label>Dialog Text</label><textarea rows="2" value={text} onChange={e => setText(e.target.value)} /></div>
          <div className="field"><label>Speaker Posture</label><input type="text" value={posture} onChange={e => setPosture(e.target.value)} /></div>
          {isCutaway && <div className="field"><label>Cutaway Description</label><textarea rows="2" value={cutaway} onChange={e => setCutaway(e.target.value)} /></div>}
        </div>
        <div className="run-row" style={{ marginTop: '.6rem' }}>
          <button className="btn-primary" onClick={save} disabled={saving} style={{ fontSize: '.8rem', padding: '.45rem 1rem' }}>
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
        <div style={{ display: 'flex', gap: '1.2rem', marginTop: '1rem', flexWrap: 'wrap', alignItems: 'flex-start' }}>
          {hasImg ? (
            <div><img className="item-image" src={`/project-files/${project}/${item.image}?t=${Date.now()}`} alt={`dialog ${index}`} /></div>
          ) : (
            <div className="item-no-image">No image yet.</div>
          )}
          {hasAudio && (
            <div style={{ marginTop: '.1rem' }}>
              <div className="mf-label" style={{ marginBottom: '.35rem' }}>Audio</div>
              <audio controls src={`/project-files/${project}/${item['audio-file']}`} style={{ height: 36, width: 220 }} />
            </div>
          )}
        </div>
        <SampleZone itemType="dialog" index={index} samplePath={item['sample-image']} project={project} />
        <div className="prompt-section">
          <div className="prompt-header"><span>Image Prompt</span></div>
          <textarea className="prompt-editor" rows="4" value={prompt} onChange={e => setPrompt(e.target.value)} />
        </div>
        <div className="run-row">
          <button className="btn-primary" onClick={regen} disabled={regenStatus === 'running'} style={{ fontSize: '.8rem', padding: '.45rem 1rem' }}>
            ⟳ Re-generate Image
            {regenStatus === 'running' && <div className="spin" style={{ display: 'inline-block', marginLeft: 8 }} />}
          </button>
        </div>
        {regenStatus === 'error' && <div className="step-log vis err">Image generation failed.</div>}
      </div>
    </div>
  );
}

function ItemsTab() {
  const { manifest, currentProject } = useContext(AppContext);
  const narr = manifest?.conversation?.narration;
  const dlg = manifest?.conversation?.dialog || [];

  if (!narr && !dlg.length) {
    return <div style={{ color: 'var(--muted)', fontSize: '.88rem', marginTop: '1rem' }}>No items yet — run the Script step first.</div>;
  }

  return (
    <div className="items-grid">
      {narr && <NarrationCard narr={narr} project={currentProject} />}
      {dlg.map((item, i) => (
        <DialogCard key={i} item={item} index={i} project={currentProject} />
      ))}
    </div>
  );
}
