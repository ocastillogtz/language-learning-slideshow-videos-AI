// api.js — thin wrappers around every backend endpoint

async function apiGet(path) {
  const r = await fetch(path);
  if (!r.ok) { const d = await r.json(); throw new Error(d.error || r.statusText); }
  return r.json();
}

async function apiPost(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || r.statusText);
  return d;
}

async function apiPostForm(path, formData) {
  const r = await fetch(path, { method: "POST", body: formData });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || r.statusText);
  return d;
}

async function apiPatch(path, body) {
  const r = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || r.statusText);
  return d;
}

async function apiDelete(path) {
  const r = await fetch(path, { method: "DELETE" });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || r.statusText);
  return d;
}

// Selectable fal.ai image models ({models:[{key,endpoint}], default_key}) —
// fetched once and shared by every dropdown (pipeline step + per-scene regen).
let _imageModelsPromise = null;
function fetchImageModels() {
  if (!_imageModelsPromise) {
    _imageModelsPromise = apiGet("/config/image_models")
      .catch(() => ({ models: [], default_key: null }));
  }
  return _imageModelsPromise;
}

function imgSrc(project, relPath) {
  return `/project-files/${project}/${relPath}?t=${Date.now()}`;
}
function audioSrc(project, relPath) {
  return `/project-files/${project}/${relPath}`;
}
