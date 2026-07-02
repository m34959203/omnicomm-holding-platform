"use client";
import { ModelRef as ModelRefData } from "@/lib/api";
import { TypeArt } from "./typeArt";

// Блок «референс модели»: КОНТУРНЫЙ РИСУНОК типа агрегата (line-art, не фото) +
// модель/бренд + краткая спека. Рисунок подбирается по типу ТС.
export default function ModelRef({ model, type }: { model?: ModelRefData | null; type?: string }) {
  const title = model?.canonical || "Модель не распознана";
  return (
    <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
      <div style={{
        width: 156, height: 96, flexShrink: 0, borderRadius: 8,
        border: "1px solid rgba(120,132,153,.25)", background: "rgba(120,132,153,.06)",
        color: "#334155", display: "flex", alignItems: "center", justifyContent: "center",
        padding: "6px 10px",
      }}>
        <TypeArt type={type} height={78} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--ink,#1b2733)", lineHeight: 1.25 }}>
          {title}
        </div>
        {model?.summary && (
          <div style={{ fontSize: 11, color: "#5b6b80", marginTop: 3, lineHeight: 1.4 }}>{model.summary}</div>
        )}
        {model?.specs && (
          <div style={{ fontSize: 10.5, color: "#8a98ac", marginTop: 4, lineHeight: 1.4 }}>{model.specs}</div>
        )}
        {model?.wiki_url && (
          <a href={model.wiki_url} target="_blank" rel="noreferrer"
            style={{ fontSize: 10.5, color: "#1f6fd6", marginTop: 4, display: "inline-block" }}>
            справка ↗
          </a>
        )}
      </div>
    </div>
  );
}
