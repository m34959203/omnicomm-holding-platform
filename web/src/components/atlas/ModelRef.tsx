"use client";
import { ModelRef as ModelRefData } from "@/lib/api";

// Референс модели в карточке — ТОЛЬКО текст (название модели + краткая справка +
// характеристики). Без картинки/контура. Нет распознанной модели → ничего не рисуем
// (тип показан бейджем рядом с заголовком).
export default function ModelRef({ model }: { model?: ModelRefData | null; type?: string }) {
  if (!model) return null;
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--ink,#1b2733)", lineHeight: 1.25 }}>
        {model.canonical}
      </div>
      {model.summary && (
        <div style={{ fontSize: 11, color: "#5b6b80", marginTop: 2, lineHeight: 1.4 }}>{model.summary}</div>
      )}
      {model.specs && (
        <div style={{ fontSize: 10.5, color: "#8a98ac", marginTop: 3, lineHeight: 1.4 }}>{model.specs}</div>
      )}
      {model.wiki_url && (
        <a href={model.wiki_url} target="_blank" rel="noreferrer"
          style={{ fontSize: 10.5, color: "#1f6fd6", marginTop: 3, display: "inline-block" }}>
          справка ↗
        </a>
      )}
    </div>
  );
}
