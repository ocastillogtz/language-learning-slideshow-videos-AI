// AppContext.js — global app state shared across all components
const { createContext, useContext, useState, useRef, useCallback } = React;

const AppCtx = createContext(null);

function AppProvider({ children }) {
  const [projects,        setProjects]       = useState([]);
  const [currentProject, setCurrentProject] = useState(null);
  const [manifest,        setManifest]       = useState(null);
  const [characters,      setCharacters]     = useState([]);
  const [locations,       setLocations]      = useState([]);
  const pollsRef = useRef({});   // { stepKey: intervalId }

  // ── API helpers ────────────────────────────────────────────────────────────

  const toast = useCallback((title, msg, type = "ok") => {
    const wrap = document.getElementById("toasts");
    if (!wrap) return;
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.innerHTML = `<strong>${title}</strong> ${msg}`;
    wrap.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }, []);

  const reloadManifest = useCallback(async (name) => {
    const pname = name || currentProject;
    if (!pname) return null;
    try {
      const r = await fetch(`/projects/${pname}`);
      const m = await r.json();
      setManifest(m);
      return m;
    } catch { return null; }
  }, [currentProject]);

  const refreshSidebar = useCallback(async () => {
    try {
      const r    = await fetch("/projects");
      const data = await r.json();
      // Guard: always store an array even if the server returned an error object
      setProjects(Array.isArray(data) ? data : []);
    } catch {}
  }, []);

  const loadAssets = useCallback(async () => {
    try {
      const [cr, lr] = await Promise.all([
        fetch("/assets/characters"), fetch("/assets/locations")
      ]);
      const charsData = await cr.json();
      const locsData  = await lr.json();
      // Both endpoints now return dicts — extract sorted key arrays for dropdowns
      setCharacters(Array.isArray(charsData) ? charsData : Object.keys(charsData).sort());
      setLocations( Array.isArray(locsData)  ? locsData  : Object.keys(locsData).sort());
    } catch {}
  }, []);

  // Poll a step until it leaves "running" state
  const startPoll = useCallback((projectName, stepKey, onDone) => {
    if (pollsRef.current[stepKey]) clearInterval(pollsRef.current[stepKey]);
    pollsRef.current[stepKey] = setInterval(async () => {
      try {
        const r = await fetch(`/projects/${projectName}/status/${stepKey}`);
        const s = await r.json();
        if (s.status !== "running") {
          clearInterval(pollsRef.current[stepKey]);
          delete pollsRef.current[stepKey];
          onDone(s);
        }
      } catch {}
    }, 2200);
  }, []);

  const stopAllPolls = useCallback(() => {
    Object.values(pollsRef.current).forEach(clearInterval);
    pollsRef.current = {};
  }, []);

  return (
    <AppCtx.Provider value={{
      projects, setProjects,
      currentProject, setCurrentProject,
      manifest, setManifest,
      characters, locations,
      toast, reloadManifest, refreshSidebar,
      loadAssets, startPoll, stopAllPolls,
    }}>
      {children}
    </AppCtx.Provider>
  );
}

function useApp() { return useContext(AppCtx); }
