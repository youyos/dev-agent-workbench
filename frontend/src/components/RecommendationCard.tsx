import { ClipboardList, ExternalLink } from "lucide-react";

import type { RecommendationItem, RecommendationPlan } from "../types";

export function RecommendationCard({ plan }: { plan: RecommendationPlan }) {
  return (
    <article className={`recommendation-card card-${plan.card_type}`}>
      <header className="recommendation-card-header">
        <span className="recommendation-card-icon"><ClipboardList size={17} /></span>
        <div>
          <span className="eyebrow">RECOMMENDATION · {plan.card_type}</span>
          <h2>{plan.title}</h2>
          {plan.description && <p>{plan.description}</p>}
        </div>
      </header>
      <div className="recommendation-sections">
        {plan.sections.map((section, sectionIndex) => (
          <section key={section.key || `${section.title}-${sectionIndex}`}>
            <div className="recommendation-section-title">
              <strong>{section.title}</strong>
              <span>{section.items.length}</span>
            </div>
            <div className="recommendation-items">
              {section.items.map((item, itemIndex) => (
                <RecommendationRow item={item} key={item.id || `${item.title}-${itemIndex}`} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </article>
  );
}

function RecommendationRow({ item }: { item: RecommendationItem }) {
  const extras = Object.entries(item).filter(
    ([key, value]) =>
      !["id", "type", "title", "url", "action_label"].includes(key)
      && value !== null
      && value !== undefined
      && typeof value !== "object",
  );
  const safeUrl = safeRecommendationUrl(item.url);
  return (
    <div className="recommendation-row">
      <span className="recommendation-type">{item.type || "作业"}</span>
      <div className="recommendation-info">
        <strong>{item.title}</strong>
        {extras.length > 0 && (
          <span>{extras.map(([key, value]) => `${key}：${String(value)}`).join(" · ")}</span>
        )}
      </div>
      {safeUrl ? (
        <a href={safeUrl} target="_blank" rel="noreferrer">
          {item.action_label || "查看"}<ExternalLink size={11} />
        </a>
      ) : (
        <button disabled>{item.action_label || "查看"}</button>
      )}
    </div>
  );
}

function safeRecommendationUrl(rawUrl?: string): string {
  if (!rawUrl) return "";
  try {
    const url = new URL(rawUrl, window.location.href);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}
