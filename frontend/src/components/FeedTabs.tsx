import { useRef } from "react";
import type { FeedTab } from "../types";

interface FeedTabsProps {
  active: FeedTab;
  onChange: (t: FeedTab) => void;
  /** When false, the Nearby tab is disabled (no geolocation). */
  nearbyEnabled: boolean;
}

const TABS: { id: FeedTab; label: string }[] = [
  { id: "global", label: "Global" },
  { id: "nearby", label: "Nearby" },
];

/**
 * Sticky text-only segmented control above the feed. Switches between
 * Global (recency-sorted, unfiltered) and Nearby (client-side adaptive
 * radius around the viewer). Tab strip lives in component state — no
 * route change on switch, no reload, no scroll jump.
 */
export function FeedTabs({ active, onChange, nearbyEnabled }: FeedTabsProps) {
  const buttonRefs = useRef<Record<FeedTab, HTMLButtonElement | null>>({
    global: null,
    nearby: null,
  });

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const enabledTabs = TABS.filter((t) => t.id === "global" || nearbyEnabled);
    const currentIdx = enabledTabs.findIndex((t) => t.id === active);
    if (currentIdx === -1) return;
    const dir = e.key === "ArrowRight" ? 1 : -1;
    const next = enabledTabs[(currentIdx + dir + enabledTabs.length) % enabledTabs.length];
    if (next.id !== active) {
      onChange(next.id);
      buttonRefs.current[next.id]?.focus();
      e.preventDefault();
    }
  }

  return (
    <div
      role="tablist"
      aria-label="Feed scope"
      onKeyDown={handleKeyDown}
      className="sticky top-[96px] z-10 bg-surface border-b border-hairline"
    >
      <div className="mx-auto max-w-[640px] flex items-stretch px-5">
        {TABS.map((t) => {
          const isActive = active === t.id;
          const isDisabled = t.id === "nearby" && !nearbyEnabled;
          return (
            <button
              key={t.id}
              ref={(el) => {
                buttonRefs.current[t.id] = el;
              }}
              type="button"
              role="tab"
              aria-selected={isActive}
              aria-disabled={isDisabled || undefined}
              disabled={isDisabled}
              tabIndex={isActive ? 0 : -1}
              onClick={() => {
                if (!isDisabled && !isActive) onChange(t.id);
              }}
              title={isDisabled ? "Enable location to see nearby clips" : undefined}
              className={[
                "relative flex-1 py-3 text-[13px] font-bold uppercase tracking-[0.12em]",
                "transition-colors",
                isActive
                  ? "text-ink-primary"
                  : isDisabled
                    ? "text-ink-primary/30 cursor-not-allowed"
                    : "text-ink-primary/50 hover:text-ink-primary/80",
              ].join(" ")}
            >
              {t.label}
              {isActive && (
                <span
                  aria-hidden
                  className="absolute left-1/2 -translate-x-1/2 bottom-0 h-[3px] w-10 rounded-full bg-gradient-to-r from-coral-light to-coral"
                />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
