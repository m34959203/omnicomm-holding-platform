"use client";
import { useState } from "react";
import { login } from "@/lib/api";
import { C, FONT } from "@/lib/atlas";

export default function Login({ onDone }: { onDone: () => void }) {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try { await login(u.trim(), p); onDone(); }
    catch { setErr("Неверный логин или пароль"); }
    finally { setBusy(false); }
  };

  const input: React.CSSProperties = {
    width: "100%", padding: "10px 12px", fontSize: 14, color: C.ink, background: "#fff",
    border: `1px solid ${C.railLine}`, borderRadius: 7, marginTop: 6, fontFamily: FONT, boxSizing: "border-box",
  };

  return (
    <div style={{ height: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: C.bg, fontFamily: FONT }}>
      <form onSubmit={submit} style={{ width: 320, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 10, boxShadow: "0 4px 24px rgba(20,30,50,.10)", padding: 28 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <div style={{ width: 12, height: 12, borderRadius: 2, background: C.blue, transform: "rotate(45deg)" }} />
          <span style={{ fontSize: 16, fontWeight: 700, color: C.ink }}>Автопарк КАП</span>
        </div>
        <div style={{ fontSize: 12, color: C.faint, marginBottom: 18 }}>Omnicomm Holding · аналитика</div>

        <label style={{ fontSize: 11.5, color: C.muted2, fontWeight: 600 }}>Логин
          <input value={u} onChange={(e) => setU(e.target.value)} autoFocus autoComplete="username" style={input} />
        </label>
        <label style={{ fontSize: 11.5, color: C.muted2, fontWeight: 600, display: "block", marginTop: 14 }}>Пароль
          <input type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" style={input} />
        </label>

        {err && <div style={{ fontSize: 12, color: C.red, marginTop: 12 }}>{err}</div>}

        <button type="submit" disabled={busy || !u || !p}
          style={{ width: "100%", marginTop: 20, padding: "10px 0", border: "none", borderRadius: 7, background: C.blue, color: "#fff", fontSize: 14, fontWeight: 600, cursor: busy ? "wait" : "pointer", opacity: (!u || !p) ? 0.5 : 1, fontFamily: FONT }}>
          {busy ? "Вход…" : "Войти"}
        </button>
      </form>
    </div>
  );
}
