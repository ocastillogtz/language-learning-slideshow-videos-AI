// ManifestTab.js
function ManifestTab() {
  const { manifest } = useApp();
  const m    = manifest || {};
  const meta = m.project_metadata  || {};
  const gen  = m.generation_config || {};
  const vi   = m.video_info        || {};
  const pipe = m.pipeline_config   || {};
  const scenes = m.scenes || [];

  // ── Derived values ────────────────────────────────────────────────────────

  const created = meta.creation_date
    ? new Date(meta.creation_date).toLocaleString("de-DE", {
        dateStyle: "medium", timeStyle: "short"
      })
    : "—";

  const updated = meta.update_date
    ? new Date(meta.update_date).toLocaleString("de-DE", {
        dateStyle: "medium", timeStyle: "short"
      })
    : "—";

  const tags = (vi.tags || "")
    .split(/[\s,]+/)
    .filter(t => t.length > 0)
    .map(t => t.startsWith("#") ? t : `#${t}`)
    .map(t => <span key={t} className="tag">{t}</span>);

  const chars      = gen.characters || [];
  const words      = gen.words || [];

  // Scenes by category
  const narrationScene  = scenes.find(s => s._is_narration);
  const dialogScenes    = scenes.filter(s =>
    !s._is_narration && !s._is_repetition &&
    s.audio?.type === "tts" && s.description?.startsWith("dialog_")
  );
  const repetitionScenes = scenes.filter(s => s._is_repetition);

  // Scene timeline pip type
  function pipType(s) {
    if (s._is_narration)                    return "narration";
    if (s._is_repetition)                   return "repetition";
    if (s.audio?.type === "sfx")            return "bell";
    if (s.description === "pause")          return "pause";
    if (s.description?.startsWith("dialog_")) return "dialog";
    return "other";
  }

  const scenePips = scenes.map((s, i) => {
    const t = pipType(s);
    return <div key={i} className={`scene-pip ${t}`} title={`${s.id}: ${t}`}/>;
  });

  return (
    <div className="mf-grid">

      {/* Overview */}
      <div className="mf-card">
        <div className="mf-label">Overview</div>
        <div style={{display:"flex",flexDirection:"column",gap:".35rem",fontSize:".84rem"}}>
          {[
            ["Created",  created],
            ["Updated",  updated],
            ["Type",     meta.project_type_key || "—"],
            ["Level",    gen.level             || "—"],
            ["Location", gen.location_key      || "—"],
            ["Scenes",   scenes.length],
            ["Dialog",   dialogScenes.length],
            ["Reps",     repetitionScenes.length],
          ].map(([k, v]) => (
            <div key={k}>
              <span style={{color:"var(--muted)", display:"inline-block", minWidth:"78px"}}>{k}</span>
              {v}
            </div>
          ))}
        </div>
      </div>

      {/* Characters */}
      <div className="mf-card">
        <div className="mf-label">Characters</div>
        {chars.length ? chars.map(name => (
          <div key={name} className="char-chip">
            <div className="char-av">{name[0]}</div>
            <div>
              <div className="char-n">{name}</div>
            </div>
          </div>
        )) : <span style={{color:"var(--muted)"}}>—</span>}
      </div>

      {/* Tags */}
      <div className="mf-card">
        <div className="mf-label">Tags</div>
        {tags.length ? tags : <span style={{color:"var(--muted)"}}>—</span>}
      </div>

      {/* Title */}
      {vi.title && (
        <div className="mf-card">
          <div className="mf-label">Video Title</div>
          <div className="mf-val">{vi.title}</div>
        </div>
      )}

      {/* Scene timeline */}
      <div className="mf-card full">
        <div className="mf-label">Scene Timeline ({scenes.length} scenes)</div>
        <div className="scene-bar">{scenePips}</div>
        <div style={{display:"flex",gap:".8rem",marginTop:".5rem",flexWrap:"wrap"}}>
          {[
            ["narration", "var(--blue)"],
            ["dialog",    "var(--accent)"],
            ["repetition","var(--purple)"],
            ["bell",      "var(--orange)"],
            ["pause",     "var(--border)"],
          ].map(([t, c]) => (
            <span key={t} style={{display:"flex",alignItems:"center",gap:".35rem",
              fontSize:".72rem",color:"var(--muted)"}}>
              <span style={{width:"10px",height:"10px",borderRadius:"2px",
                background:c,display:"inline-block"}}/>
              {t}
            </span>
          ))}
        </div>
      </div>

      {/* Word list (word_learning type) */}
      {words.length > 0 && (
        <div className="mf-card full">
          <div className="mf-label">Word List</div>
          {words.map(w => (
            <span key={w} className="tag"
              style={{background:"rgba(167,139,250,.14)",
                borderColor:"rgba(167,139,250,.25)",color:"var(--purple)"}}>
              {w}
            </span>
          ))}
        </div>
      )}

      {/* Compact dialog */}
      {gen.compact_dialog && (
        <div className="mf-card full">
          <div className="mf-label">Compact Dialog</div>
          <div className="mf-val" style={{whiteSpace:"pre-wrap"}}>{gen.compact_dialog}</div>
        </div>
      )}

      {/* Dialog auto-evaluation */}
      {gen.dialog_auto_evaluation && Object.keys(gen.dialog_auto_evaluation).length > 0 && (
        <div className="mf-card full">
          <div className="mf-label">Dialog Auto-Evaluation</div>
          {gen.dialog_auto_evaluation._truncated && (
            <div style={{
              padding:".6rem .75rem", marginBottom:".55rem",
              background:"var(--s2)", borderRadius:"8px",
              borderLeft:"3px solid var(--orange)",
              fontSize:".8rem", color:"var(--orange)",
            }}>
              {gen.dialog_auto_evaluation._truncated}
            </div>
          )}
          {Object.entries(gen.dialog_auto_evaluation).filter(([key]) => key !== "_truncated").map(([key, verdict]) => {
            const idx     = parseInt(key.replace("dialog_", ""), 10);
            const scene   = dialogScenes[idx];
            const speaker = scene?.characters?.[0] || "—";
            const text    = scene?.subtitle_text   || "";
            const lower   = (verdict || "").toLowerCase();
            const isGood  = lower.startsWith("excellent") || lower.startsWith("good") || lower.startsWith("great") || lower.startsWith("natural");
            const isBad   = lower.startsWith("bad") || lower.startsWith("wrong") || lower.startsWith("incorrect") || lower.startsWith("error");
            const dotColor = isGood ? "var(--green)" : isBad ? "var(--red)" : "var(--orange)";
            return (
              <div key={key} style={{
                display:"flex", flexDirection:"column", gap:".3rem",
                padding:".6rem .75rem", marginBottom:".45rem",
                background:"var(--s2)", borderRadius:"8px",
                borderLeft:`3px solid ${dotColor}`,
              }}>
                <div style={{display:"flex", alignItems:"center", gap:".5rem", fontSize:".78rem"}}>
                  <span className="dlg-sp" style={{fontSize:".72rem",padding:".15rem .45rem"}}>{speaker}</span>
                  <span style={{color:"var(--text)", fontStyle:"italic", opacity:.8}}>{text}</span>
                </div>
                <div style={{fontSize:".8rem", color: isGood ? "var(--green)" : isBad ? "var(--red)" : "var(--orange)"}}>
                  {verdict}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Provided context */}
      <div className="mf-card full">
        <div className="mf-label">Provided Context</div>
        <div className="mf-val">{gen.provided_context || "—"}</div>
      </div>

      {/* Learning points */}
      <div className="mf-card full">
        <div className="mf-label">Learning Points</div>
        <div className="mf-val">{gen.provided_learning_points || "—"}</div>
      </div>

      {/* Narration */}
      {narrationScene?.subtitle_text && (
        <div className="mf-card full">
          <div className="mf-label">Narration</div>
          <div className="mf-val italic">{narrationScene.subtitle_text}</div>
        </div>
      )}

      {/* Grammar insights */}
      {vi.insights && (
        <div className="mf-card full">
          <div className="mf-label">Grammar Insights</div>
          <div className="mf-val">{vi.insights}</div>
        </div>
      )}

      {/* Dialogue */}
      <div className="mf-card full">
        <div className="mf-label">Dialogue ({dialogScenes.length} lines)</div>
        {dialogScenes.length ? dialogScenes.map((s, i) => (
          <div key={s.id} className="dlg-row">
            <span className="dlg-sp">{s.characters?.[0] || "—"}</span>
            <div style={{flex:1}}>
              <div className="dlg-tx">{s.subtitle_text}</div>
              {s.scene_visual && (
                <div style={{fontSize:".74rem",color:"var(--muted)",fontStyle:"italic",
                  marginTop:".25rem"}}>
                  {s.scene_visual}
                </div>
              )}
            </div>
          </div>
        )) : <span style={{color:"var(--muted)"}}>No dialogue yet — run the Script step first.</span>}
      </div>

      {/* Repetitions */}
      {repetitionScenes.length > 0 && (
        <div className="mf-card full">
          <div className="mf-label">Shadowing Repetitions ({repetitionScenes.length})</div>
          {repetitionScenes.map((s, i) => (
            <div key={s.id} className="dlg-row">
              <span className="dlg-sp" style={{background:"var(--purple)",color:"#0d0d10"}}>
                R{i + 1}
              </span>
              <span className="dlg-tx">{s.subtitle_text}</span>
            </div>
          ))}
        </div>
      )}

      {/* Pipeline config */}
      <div className="mf-card">
        <div className="mf-label">Pipeline Config</div>
        <div style={{display:"flex",flexDirection:"column",gap:".35rem",fontSize:".84rem"}}>
          {[
            ["Inter-pause",  `${pipe.inter_pause_ms ?? "—"} ms`],
            ["Rep factor",   pipe.repetition_pause_factor ?? "—"],
          ].map(([k, v]) => (
            <div key={k}>
              <span style={{color:"var(--muted)",display:"inline-block",minWidth:"96px"}}>{k}</span>
              {v}
            </div>
          ))}
        </div>
      </div>

    </div>
  );
}
