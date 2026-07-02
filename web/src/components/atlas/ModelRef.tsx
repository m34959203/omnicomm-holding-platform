"use client";
import { useState } from "react";
import { ModelRef as ModelRefData } from "@/lib/api";
import { TypeIcon } from "./typeIcons";

// Блок «референс модели»: миниатюра фото (локальная /models/<slug>.jpg → внешний
// URL → иконка по типу) + модель/бренд + краткая спека. Клик по фото → зум.
export default function ModelRef({ model, type }: { model?: ModelRefData | null; type?: string }) {
  const [zoom, setZoom] = useState(false);
  const [broken, setBroken] = useState(false);

  const src = !broken
    ? (model?.image_slug ? `/models/${model.image_slug}.jpg` : model?.image_url || null)
    : (model?.image_url && !model.image_slug ? null : model?.image_url || null);
  const hasPhoto = !!src && !broken;

  const thumb = (
    <div
      onClick={hasPhoto ? () => setZoom(true) : undefined}
      style={{
        width: 132, height: 84, flexShrink: 0, borderRadius: 8, overflow: "hidden",
        border: "1px solid rgba(120,132,153,.25)", background: "rgba(120,132,153,.08)",
        display: "flex", alignItems: "center", justifyContent: "center",
        color: "#748499", cursor: hasPhoto ? "zoom-in" : "default",
      }}>
      {hasPhoto ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src!} alt={model?.canonical || "модель"} onError={() => setBroken(true)}
          style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      ) : (
        <TypeIcon type={type} size={44} />
      )}
    </div>
  );

  return (
    <>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
        {thumb}
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--ink,#1b2733)", lineHeight: 1.25 }}>
            {model?.canonical || "Модель не распознана"}
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

      {zoom && hasPhoto && (
        <div onClick={() => setZoom(false)}
          style={{ position: "fixed", inset: 0, zIndex: 70, background: "rgba(0,0,0,.8)",
            display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={src!} alt={model?.canonical || "модель"}
            style={{ maxWidth: "92vw", maxHeight: "88vh", objectFit: "contain", borderRadius: 8 }} />
        </div>
      )}
    </>
  );
}
