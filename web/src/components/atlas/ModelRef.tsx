"use client";
import { useMemo, useState } from "react";
import { ModelRef as ModelRefData } from "@/lib/api";
import { TypeIcon } from "./typeIcons";

// Блок «референс модели»: каскад изображения — фото КОНКРЕТНОЙ модели
// (/models/<slug>.jpg → внешний URL) → фото ТИПА агрегата (/models/type-<type>.jpg)
// → SVG-иконка по типу. Клик по фото → зум. Так фото есть у всего парка, а не у
// горстки моделей.
export default function ModelRef({ model, type }: { model?: ModelRefData | null; type?: string }) {
  const [zoom, setZoom] = useState(false);
  const [idx, setIdx] = useState(0);

  const candidates = useMemo(() => {
    const c: string[] = [];
    if (model?.image_slug) c.push(`/models/${model.image_slug}.jpg`);
    if (model?.image_url) c.push(model.image_url);
    if (type) c.push(`/models/type-${type}.jpg`);
    return c;
  }, [model?.image_slug, model?.image_url, type]);

  const src = idx < candidates.length ? candidates[idx] : null;
  const hasPhoto = !!src;
  const title = model?.canonical || "Модель не распознана";

  const thumb = (
    <div
      onClick={hasPhoto ? () => setZoom(true) : undefined}
      style={{
        width: 148, height: 92, flexShrink: 0, borderRadius: 8, overflow: "hidden",
        border: "1px solid rgba(120,132,153,.25)", background: "rgba(120,132,153,.08)",
        display: "flex", alignItems: "center", justifyContent: "center",
        color: "#748499", cursor: hasPhoto ? "zoom-in" : "default",
      }}>
      {hasPhoto ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src!} alt={title} onError={() => setIdx((i) => i + 1)}
          style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      ) : (
        <TypeIcon type={type} size={48} />
      )}
    </div>
  );

  return (
    <>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
        {thumb}
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

      {zoom && hasPhoto && (
        <div onClick={() => setZoom(false)}
          style={{ position: "fixed", inset: 0, zIndex: 70, background: "rgba(0,0,0,.8)",
            display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={src!} alt={title}
            style={{ maxWidth: "92vw", maxHeight: "88vh", objectFit: "contain", borderRadius: 8 }} />
        </div>
      )}
    </>
  );
}
