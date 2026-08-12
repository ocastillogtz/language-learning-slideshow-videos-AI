// ConnectionsTab.js — social publishing connections (YouTube · Instagram · Facebook)
// View non-sensitive connection parameters + live status, test each connection,
// and set up / reset credentials. Secrets never leave the backend — this page
// only ever sees presence booleans, identifiers, and status.

// ── Shared bits ────────────────────────────────────────────────────────────────

function StatusBanner({ ok, children }) {
  return (
    <div style={{
      padding: ".5rem .75rem", borderRadius: 6, marginBottom: ".75rem", fontSize: ".8rem",
      background: ok ? "rgba(74,222,128,.12)" : "rgba(248,113,113,.12)",
      color: ok ? "var(--green)" : "var(--red)",
      border: `1px solid ${ok ? "rgba(74,222,128,.3)" : "rgba(248,113,113,.3)"}`,
    }}>{children}</div>
  );
}

function ParamRow({ label, value, good }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      padding: ".35rem 0", borderBottom: "1px solid var(--border)", fontSize: ".8rem",
    }}>
      <span style={{ color: "var(--muted)" }}>{label}</span>
      <span style={{
        fontWeight: 500,
        color: good === true ? "var(--green)" : good === false ? "var(--red)" : "var(--text)",
      }}>{value}</span>
    </div>
  );
}

function ConnCard({ title, accent, dotOk, children }) {
  return (
    <div style={{
      background: "var(--s1)", border: "1px solid var(--border)", borderRadius: 10,
      padding: "1.15rem 1.25rem", display: "flex", flexDirection: "column",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: ".55rem", marginBottom: ".9rem" }}>
        <span style={{
          width: 9, height: 9, borderRadius: "50%",
          background: dotOk ? "var(--green)" : "var(--muted)", flexShrink: 0,
        }} />
        <div style={{ fontSize: "1rem", fontWeight: 600, color: accent }}>{title}</div>
      </div>
      {children}
    </div>
  );
}

function TestButton({ onTest }) {
  const [busy, setBusy] = React.useState(false);
  const [res,  setRes]  = React.useState(null); // { ok, detail }

  async function run() {
    setBusy(true); setRes(null);
    try {
      const d = await onTest();
      setRes(d);
    } catch (e) {
      setRes({ ok: false, detail: e.message });
    } finally { setBusy(false); }
  }

  return (
    <div style={{ marginTop: ".75rem" }}>
      <button className="btn-ghost" onClick={run} disabled={busy}
        style={{ fontSize: ".8rem" }}>
        {busy ? "Testing…" : "Test Connection"}
      </button>
      {res && (
        <div style={{
          marginTop: ".5rem", fontSize: ".78rem",
          color: res.ok ? "var(--green)" : "var(--red)", whiteSpace: "pre-wrap",
        }}>
          {res.ok ? "✓ " : "✕ "}{res.detail}
        </div>
      )}
    </div>
  );
}

function Divider() {
  return <div style={{ borderTop: "1px solid var(--border)", margin: ".9rem 0 .8rem" }} />;
}

function SubHead({ children }) {
  return (
    <div style={{ fontSize: ".82rem", fontWeight: 600, marginBottom: ".5rem", color: "var(--text)" }}>
      {children}
    </div>
  );
}

// ── YouTube ─────────────────────────────────────────────────────────────────────

function YouTubeCard({ data, reload }) {
  const [resetting, setResetting] = React.useState(false);
  const [msg, setMsg] = React.useState("");
  const d = data || {};

  async function doReset() {
    setResetting(true); setMsg("");
    try {
      const r = await fetch("/auth/youtube/reset", { method: "POST" }).then(x => x.json());
      setMsg(r.message || r.error || "Done");
      reload();
    } catch (e) { setMsg("Request failed: " + e.message); }
    finally { setResetting(false); }
  }

  return (
    <ConnCard title="YouTube" accent="var(--red)" dotOk={d.configured}>
      <StatusBanner ok={d.configured}>
        {d.configured
          ? "Authenticated — token.json present"
          : "Not authenticated — run a YouTube upload once to complete OAuth consent"}
      </StatusBanner>

      <ParamRow label="OAuth client in .env" value={d.client_env_set ? "set" : "—"} good={d.client_env_set || undefined} />
      <ParamRow label="client_secret.json" value={d.client_file_set ? "present" : "—"} />
      <ParamRow label="OAuth client configured" value={d.client_configured ? "yes" : "no"} good={d.client_configured} />
      <ParamRow label="token.json" value={d.token_exists ? "present" : "missing"} good={d.token_exists} />

      <TestButton onTest={() => apiPost("/connections/youtube/test", {})} />

      <Divider />
      <div style={{ fontSize: ".78rem", color: "var(--muted)", marginBottom: ".6rem" }}>
        The App ID/Secret can live in <code>GOOGLE_CLIENT_ID</code> / <code>GOOGLE_CLIENT_SECRET</code> in
        {" "}<code>.env</code>, or as a <code>client_secret.json</code> file. Sign-in happens in the
        browser on the first upload and is cached in <code>token.json</code>.
      </div>
      {d.configured && (
        <>
          <button className="btn-cancel" onClick={doReset} disabled={resetting} style={{ fontSize: ".8rem" }}>
            {resetting ? "Clearing…" : "Reset YouTube Login"}
          </button>
          {msg && <div style={{ marginTop: ".4rem", fontSize: ".78rem", color: "var(--muted)" }}>{msg}</div>}
        </>
      )}
    </ConnCard>
  );
}

// ── Instagram ─────────────────────────────────────────────────────────────────

function InstagramCard({ data, reload }) {
  const d = data || {};
  const [shortToken, setShortToken] = React.useState("");
  const [igUserId,   setIgUserId]   = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [setupMsg, setSetupMsg] = React.useState("");
  const [resetting, setResetting] = React.useState(false);

  async function doSetup() {
    setSaving(true); setSetupMsg("");
    try {
      const r = await fetch("/auth/instagram/setup", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ short_token: shortToken, ig_user_id: igUserId }),
      }).then(x => x.json());
      setSetupMsg(r.message || r.error || "Done");
      if (r.message) { setShortToken(""); reload(); }
    } catch (e) { setSetupMsg("Request failed: " + e.message); }
    finally { setSaving(false); }
  }

  async function doReset() {
    setResetting(true); setSetupMsg("");
    try {
      const r = await fetch("/auth/instagram/reset", { method: "POST" }).then(x => x.json());
      setSetupMsg(r.message || r.error || "Done");
      reload();
    } catch (e) { setSetupMsg("Request failed: " + e.message); }
    finally { setResetting(false); }
  }

  const envOk = d.app_id_set && d.app_secret_set;

  return (
    <ConnCard title="Instagram" accent="var(--purple)" dotOk={d.configured}>
      <StatusBanner ok={d.configured}>
        {d.configured
          ? `Connected — token valid for ${d.days_left} more day${d.days_left !== 1 ? "s" : ""}`
          : "Not configured — add a token in Setup below"}
      </StatusBanner>

      <ParamRow label="FB_APP_ID (.env)" value={d.app_id_set ? "set" : "missing"} good={d.app_id_set} />
      <ParamRow label="FB_APP_SECRET (.env)" value={d.app_secret_set ? "set" : "missing"} good={d.app_secret_set} />
      <ParamRow label="IG User ID" value={d.ig_user_id || "—"} />
      <ParamRow label="Token expires in" value={d.configured ? `${d.days_left} days` : "—"} />

      <TestButton onTest={() => apiPost("/connections/instagram/test", {})} />

      <Divider />
      <SubHead>{d.configured ? "Re-authenticate" : "Setup (one-time)"}</SubHead>
      {!envOk && (
        <div style={{ fontSize: ".76rem", color: "var(--red)", marginBottom: ".5rem" }}>
          Set <code>FB_APP_ID</code> and <code>FB_APP_SECRET</code> in <code>.env</code> first.
        </div>
      )}
      <div style={{ fontSize: ".78rem", color: "var(--muted)", marginBottom: ".6rem" }}>
        Get a short-lived token from the{" "}
        <a href="https://developers.facebook.com/tools/explorer/" target="_blank" rel="noreferrer"
           style={{ color: "var(--accent)" }}>Graph API Explorer</a>{" "}
        with <code>instagram_basic</code>, <code>instagram_content_publish</code> permissions.
      </div>
      <div className="field">
        <label>Short-Lived Token</label>
        <input value={shortToken} onChange={e => setShortToken(e.target.value)} placeholder="EAA…" />
      </div>
      <div className="field">
        <label>Instagram User ID{" "}
          <span style={{ color: "var(--muted)", fontWeight: 300 }}>(optional — auto-detected)</span></label>
        <input value={igUserId} onChange={e => setIgUserId(e.target.value)} placeholder="e.g. 17841400000000000" />
      </div>
      <div style={{ display: "flex", gap: ".5rem", alignItems: "center", marginTop: ".25rem" }}>
        <button className="btn-primary" onClick={doSetup} disabled={saving || !shortToken}
          style={{ fontSize: ".8rem" }}>
          {saving ? "Saving…" : "Save Credentials"}
        </button>
        {d.configured && (
          <button className="btn-cancel" onClick={doReset} disabled={resetting} style={{ fontSize: ".8rem" }}>
            {resetting ? "Clearing…" : "Reset"}
          </button>
        )}
      </div>
      {setupMsg && <div style={{ marginTop: ".4rem", fontSize: ".78rem", color: "var(--muted)" }}>{setupMsg}</div>}
    </ConnCard>
  );
}

// ── Facebook ──────────────────────────────────────────────────────────────────

function FacebookCard({ data, reload }) {
  const d = data || {};
  const [pageId,   setPageId]   = React.useState("");
  const [token,    setToken]    = React.useState("");
  const [isPageTk, setIsPageTk] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [setupMsg, setSetupMsg] = React.useState("");
  const [resetting, setResetting] = React.useState(false);

  async function doSetup() {
    setSaving(true); setSetupMsg("");
    try {
      const r = await fetch("/auth/facebook/setup", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page_id: pageId, token, is_page_token: isPageTk }),
      }).then(x => x.json());
      setSetupMsg(r.message || r.error || "Done");
      if (r.message) { setToken(""); reload(); }
    } catch (e) { setSetupMsg("Request failed: " + e.message); }
    finally { setSaving(false); }
  }

  async function doReset() {
    setResetting(true); setSetupMsg("");
    try {
      const r = await fetch("/auth/facebook/reset", { method: "POST" }).then(x => x.json());
      setSetupMsg(r.message || r.error || "Done");
      reload();
    } catch (e) { setSetupMsg("Request failed: " + e.message); }
    finally { setResetting(false); }
  }

  const envOk = d.app_id_set && d.app_secret_set;

  return (
    <ConnCard title="Facebook" accent="var(--blue)" dotOk={d.configured}>
      <StatusBanner ok={d.configured}>
        {d.configured
          ? `Connected to Page ${d.page_name || d.page_id}`
          : "Not configured — add a Page in Setup below"}
      </StatusBanner>

      <ParamRow label="FB_APP_ID (.env)" value={d.app_id_set ? "set" : "missing"} good={d.app_id_set} />
      <ParamRow label="FB_APP_SECRET (.env)" value={d.app_secret_set ? "set" : "missing"} good={d.app_secret_set} />
      <ParamRow label="Page" value={d.page_name || "—"} />
      <ParamRow label="Page ID" value={d.page_id || "—"} />
      <ParamRow label="Page token" value={d.configured ? (d.non_expiring ? "non-expiring" : `${d.days_left} days`) : "—"} />

      <TestButton onTest={() => apiPost("/connections/facebook/test", {})} />

      <Divider />
      <SubHead>{d.configured ? "Re-connect Page" : "Setup (one-time)"}</SubHead>
      <div style={{ fontSize: ".78rem", color: "var(--muted)", marginBottom: ".6rem" }}>
        Independent of Instagram. Paste a <strong>User Access Token</strong> (with
        {" "}<code>pages_show_list</code>, <code>pages_manage_posts</code>) and the target Page ID —
        the backend resolves the Page's own token. Or tick the box to store a Page token directly.
        {!envOk && !isPageTk && (
          <span style={{ color: "var(--red)", display: "block", marginTop: ".35rem" }}>
            A user token needs <code>FB_APP_ID</code>/<code>FB_APP_SECRET</code> in <code>.env</code>,
            or tick “token is a Page token”.
          </span>
        )}
      </div>
      <div className="field">
        <label>Page ID</label>
        <input value={pageId} onChange={e => setPageId(e.target.value)} placeholder="e.g. 1029384756" />
      </div>
      <div className="field">
        <label>Access Token</label>
        <input value={token} onChange={e => setToken(e.target.value)} placeholder="EAA…" />
      </div>
      <div className="toggle-row">
        <input type="checkbox" id="fb_is_page_tk" checked={isPageTk}
          onChange={e => setIsPageTk(e.target.checked)} />
        <label htmlFor="fb_is_page_tk">Token is already a Page token (store as-is)</label>
      </div>
      <div style={{ display: "flex", gap: ".5rem", alignItems: "center", marginTop: ".5rem" }}>
        <button className="btn-primary" onClick={doSetup} disabled={saving || !pageId || !token}
          style={{ fontSize: ".8rem" }}>
          {saving ? "Saving…" : "Connect Page"}
        </button>
        {d.configured && (
          <button className="btn-cancel" onClick={doReset} disabled={resetting} style={{ fontSize: ".8rem" }}>
            {resetting ? "Clearing…" : "Reset"}
          </button>
        )}
      </div>
      {setupMsg && <div style={{ marginTop: ".4rem", fontSize: ".78rem", color: "var(--muted)" }}>{setupMsg}</div>}
    </ConnCard>
  );
}

// ── Page ────────────────────────────────────────────────────────────────────────

function ConnectionsTab() {
  const [status, setStatus] = React.useState(null);
  const [err, setErr] = React.useState("");

  const reload = React.useCallback(() => {
    apiGet("/connections").then(setStatus).catch(e => setErr(e.message));
  }, []);

  React.useEffect(() => { reload(); }, [reload]);

  return (
    <div style={{ padding: "1.75rem 2rem", maxWidth: 1200, margin: "0 auto" }}>
      <div style={{ marginBottom: "1.4rem" }}>
        <div style={{ fontSize: "1.3rem", fontWeight: 600 }}>Connections</div>
        <div style={{ fontSize: ".82rem", color: "var(--muted)", marginTop: ".3rem" }}>
          Publishing integrations. Secret keys and tokens stay on the server (<code>.env</code> +
          local credential files) and are never shown here — only their status.
        </div>
      </div>

      {err && <StatusBanner ok={false}>Failed to load: {err}</StatusBanner>}

      <div style={{
        display: "grid", gap: "1.25rem",
        gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
      }}>
        <YouTubeCard   data={status && status.youtube}   reload={reload} />
        <InstagramCard data={status && status.instagram} reload={reload} />
        <FacebookCard  data={status && status.facebook}  reload={reload} />
      </div>
    </div>
  );
}
