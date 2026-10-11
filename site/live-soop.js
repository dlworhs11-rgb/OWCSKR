// SOOP's station API only answers real browsers, so each visitor's browser checks it (cheap, cached 2 min).
window.SoopLive = {
  async check(targets) {
    const out = {};
    await Promise.all(targets.map(async t => {
      const key = 'soop:' + t.id;
      try {
        const c = JSON.parse(sessionStorage.getItem(key) || 'null');
        if (c && Date.now() - c.at < 120000) { out[t.id] = c.v; return; }
      } catch {}
      try {
        const r = await fetch(`https://chapi.sooplive.com/api/${encodeURIComponent(t.id)}/station`);
        if (!r.ok) return;
        const j = await r.json();
        const v = j.broad ? { live: true, title: j.broad.broad_title || '', viewers: Number(j.broad.current_sum_viewer) || null } : { live: false };
        out[t.id] = v;
        try { sessionStorage.setItem(key, JSON.stringify({ at: Date.now(), v })); } catch {}
      } catch { /* offline or blocked: treat as unknown */ }
    }));
    return out;
  }
};
