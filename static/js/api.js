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

function imgSrc(project, relPath) {
  return `/project-files/${project}/${relPath}?t=${Date.now()}`;
}
function audioSrc(project, relPath) {
  return `/project-files/${project}/${relPath}`;
}
