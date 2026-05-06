const { useState, useContext } = React;

function NewProjectModal({ onClose }) {
  const { refreshProjects, selectProject, addToast } = useContext(AppContext);
  const [name, setName] = useState('');
  const [scene, setScene] = useState('');
  const [learning, setLearning] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!name || !scene || !learning) {
      setError('Fill in all fields.');
      return;
    }
    setSubmitting(true);
    try {
      await apiPost('/create_project', { project_name: name, scene, learning });
      addToast('Created!', `Project "${name}" created.`, 'ok');
      onClose();
      setName(''); setScene(''); setLearning(''); setError('');
      await refreshProjects();
      await selectProject(name);
    } catch (e) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-bg open" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal-box">
        <div className="modal-hdr">
          <h3>New Project</h3>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div className="field">
              <label>Project Name</label>
              <input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. cafe_talk_b1" />
            </div>
            <div className="field">
              <label>Scene Description</label>
              <textarea rows="4" value={scene} onChange={e => setScene(e.target.value)} placeholder="Describe the scene setting and characters…" />
            </div>
            <div className="field">
              <label>Learning Points</label>
              <textarea rows="3" value={learning} onChange={e => setLearning(e.target.value)} placeholder="What language points should be covered?" />
            </div>
            {error && <div className="err-msg" style={{ display: 'block' }}>{error}</div>}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn-cancel" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn-primary" disabled={submitting}>
              {submitting ? 'Creating…' : 'Create Project'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ToastContainer() {
  const { toasts } = useContext(AppContext);
  return (
    <div className="toasts">
      {toasts.map(t => (
        <div key={t.id} className={`toast ${t.type}`}>
          <strong>{t.title}</strong> {t.msg}
        </div>
      ))}
    </div>
  );
}
