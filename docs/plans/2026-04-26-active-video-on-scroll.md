# Active Video on Scroll Implementation Plan

**Purpose:** After this change, scrolling the feed causes whichever `SegmentCard` is currently most visible in the viewport to be the only one playing — other cards pause. Today, only the top card (`i === 0`) ever auto-plays regardless of scroll position.

**Architecture:** A single `IntersectionObserver` (owned by `FeedShell`) tracks the visibility ratio of each card. The card with the highest ratio is the "active" card; its index is passed down so each `SegmentCard` can `play()`/`pause()` its `<video>` ref via an effect. The existing `priority` prop is replaced by `active`. No external libraries — IntersectionObserver is supported on iOS Safari 12.2+.

**Tech Stack:** React 18, TypeScript, Vite, Vitest, jsdom. Uses native `IntersectionObserver` (browser) — mocked in tests.

**Codebase Orientation:**
- Entry point: `frontend/src/main.tsx` → `frontend/src/App.tsx`
- Feed view: `frontend/src/views/Feed.tsx` — fetches segments + renders `<FeedShell>`
- List shell: `frontend/src/components/FeedShell.tsx:13-32` — maps segments to `<SegmentCard>` items in an `<ol>`
- Card: `frontend/src/components/SegmentCard.tsx:13-126` — owns the `<video>` element; today `autoPlay={priority}`
- Test runner: `pnpm test` (run from `frontend/`); existing jsdom-based vitest setup at `frontend/vitest.config.ts`
- Sample existing test: `frontend/src/components/RecordButton.test.tsx` — pattern for `createRoot` + `act()` in vitest

**Key constraints (from CLAUDE.md):**
- iOS Safari is the demo target — `playsInline`, `muted`, and `<video>.play()` returning a promise that may reject without user gesture must all be handled.
- This is a 60-second / 4-clip demo; do not over-engineer. No virtualization, no scroll throttling beyond the observer itself.

---

## Milestone 1: Active-index detection

**Goal:** A reusable hook that, given a list of element refs, reports the index of the one with the highest `intersectionRatio`.

**Acceptance test:** `pnpm test` passes for the new `useMostVisibleIndex.test.tsx` file.

### Task 1: Pure helper — `pickMaxRatioIndex`

**Behavioral check:** `node -e "console.log(require('./frontend/dist/...'))"` not needed — this is unit-tested. After Step 4, `pnpm test -- pickMaxRatioIndex` shows 3 passing tests.

**Files:**
- Create: `frontend/src/hooks/pickMaxRatioIndex.ts`
- Create: `frontend/src/hooks/pickMaxRatioIndex.test.ts`

**Step 1: Write the failing test**

Create `frontend/src/hooks/pickMaxRatioIndex.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { pickMaxRatioIndex } from "./pickMaxRatioIndex";

describe("pickMaxRatioIndex", () => {
  it("returns the index of the highest ratio", () => {
    expect(pickMaxRatioIndex([0.1, 0.7, 0.3])).toBe(1);
  });

  it("returns 0 when all ratios are equal", () => {
    expect(pickMaxRatioIndex([0.5, 0.5, 0.5])).toBe(0);
  });

  it("returns -1 when no ratio exceeds 0", () => {
    expect(pickMaxRatioIndex([0, 0, 0])).toBe(-1);
  });

  it("returns -1 for empty input", () => {
    expect(pickMaxRatioIndex([])).toBe(-1);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test -- pickMaxRatioIndex`
Expected: FAIL — "Cannot find module './pickMaxRatioIndex'".

**Step 3: Write minimal implementation**

Create `frontend/src/hooks/pickMaxRatioIndex.ts`:

```typescript
/**
 * Returns the index of the largest value in `ratios`.
 * Returns -1 if the array is empty or every value is <= 0
 * (i.e. nothing is visible at all).
 * Ties resolve to the lowest index.
 */
export function pickMaxRatioIndex(ratios: number[]): number {
  let maxIdx = -1;
  let maxVal = 0;
  for (let i = 0; i < ratios.length; i++) {
    if (ratios[i] > maxVal) {
      maxVal = ratios[i];
      maxIdx = i;
    }
  }
  return maxIdx;
}
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm test -- pickMaxRatioIndex`
Expected: PASS — 4 passing tests.

**Step 5: Commit**

```bash
git add frontend/src/hooks/pickMaxRatioIndex.ts frontend/src/hooks/pickMaxRatioIndex.test.ts
git commit -m "feat(feed): add pickMaxRatioIndex helper for active-card detection"
```

---

### Task 2: `useMostVisibleIndex` hook

**Behavioral check:** Hook test asserts that, after firing fake `IntersectionObserver` entries, the returned index reflects the entry with the highest ratio.

**Files:**
- Create: `frontend/src/hooks/useMostVisibleIndex.ts`
- Create: `frontend/src/hooks/useMostVisibleIndex.test.tsx`

**Step 1: Write the failing test**

Create `frontend/src/hooks/useMostVisibleIndex.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import { useRef, useEffect } from "react";
import { useMostVisibleIndex } from "./useMostVisibleIndex";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type IOCallback = (entries: Array<{ target: Element; intersectionRatio: number }>) => void;

let lastCallback: IOCallback | null = null;
const observed = new Set<Element>();

class FakeIntersectionObserver {
  constructor(cb: IOCallback) {
    lastCallback = cb;
  }
  observe(el: Element) { observed.add(el); }
  unobserve(el: Element) { observed.delete(el); }
  disconnect() { observed.clear(); }
}

beforeEach(() => {
  lastCallback = null;
  observed.clear();
  (globalThis as unknown as { IntersectionObserver: typeof FakeIntersectionObserver })
    .IntersectionObserver = FakeIntersectionObserver;
});

let mounted: { container: HTMLDivElement; root: Root }[] = [];

afterEach(() => {
  mounted.forEach(({ root, container }) => {
    act(() => root.unmount());
    container.remove();
  });
  mounted = [];
});

function Harness({ count, onIndex }: { count: number; onIndex: (i: number) => void }) {
  const refs = useRef<(HTMLDivElement | null)[]>([]);
  const idx = useMostVisibleIndex(refs, count);
  useEffect(() => { onIndex(idx); }, [idx, onIndex]);
  return (
    <div>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} ref={(el) => { refs.current[i] = el; }} data-idx={i} />
      ))}
    </div>
  );
}

function render(count: number, onIndex: (i: number) => void) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(<Harness count={count} onIndex={onIndex} />);
  });
  mounted.push({ container, root });
  return container;
}

describe("useMostVisibleIndex", () => {
  it("returns -1 before any intersection entries fire", () => {
    const onIndex = vi.fn();
    render(3, onIndex);
    expect(onIndex).toHaveBeenLastCalledWith(-1);
  });

  it("reports the index of the most-visible element", () => {
    const onIndex = vi.fn();
    const container = render(3, onIndex);
    const els = container.querySelectorAll("[data-idx]");

    act(() => {
      lastCallback!([
        { target: els[0], intersectionRatio: 0.2 },
        { target: els[1], intersectionRatio: 0.9 },
        { target: els[2], intersectionRatio: 0.1 },
      ]);
    });

    expect(onIndex).toHaveBeenLastCalledWith(1);
  });

  it("updates when ratios change in subsequent batches", () => {
    const onIndex = vi.fn();
    const container = render(3, onIndex);
    const els = container.querySelectorAll("[data-idx]");

    act(() => {
      lastCallback!([{ target: els[0], intersectionRatio: 0.8 }]);
    });
    expect(onIndex).toHaveBeenLastCalledWith(0);

    act(() => {
      lastCallback!([
        { target: els[0], intersectionRatio: 0.1 },
        { target: els[2], intersectionRatio: 0.7 },
      ]);
    });
    expect(onIndex).toHaveBeenLastCalledWith(2);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test -- useMostVisibleIndex`
Expected: FAIL — "Cannot find module './useMostVisibleIndex'".

**Step 3: Write minimal implementation**

Create `frontend/src/hooks/useMostVisibleIndex.ts`:

```typescript
import { useEffect, useRef, useState, type RefObject } from "react";
import { pickMaxRatioIndex } from "./pickMaxRatioIndex";

/**
 * Watches a fixed-length array of element refs and returns the index
 * of the one currently with the highest IntersectionObserver ratio.
 *
 * Returns -1 when nothing is visible (e.g. before first paint).
 *
 * `refs.current` is read on every observer callback, so callers
 * should populate it via `ref={(el) => { refs.current[i] = el; }}`.
 */
export function useMostVisibleIndex(
  refs: RefObject<(HTMLElement | null)[]>,
  count: number,
): number {
  const [activeIdx, setActiveIdx] = useState(-1);
  const ratiosRef = useRef<number[]>([]);

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    if (count === 0) {
      setActiveIdx(-1);
      return;
    }

    ratiosRef.current = new Array(count).fill(0);

    const observer = new IntersectionObserver(
      (entries) => {
        const list = refs.current ?? [];
        for (const entry of entries) {
          const idx = list.indexOf(entry.target as HTMLElement);
          if (idx !== -1) {
            ratiosRef.current[idx] = entry.intersectionRatio;
          }
        }
        setActiveIdx(pickMaxRatioIndex(ratiosRef.current));
      },
      // Multiple thresholds give us granular ratio updates as the user scrolls.
      { threshold: [0, 0.1, 0.25, 0.5, 0.75, 1] },
    );

    const list = refs.current ?? [];
    for (const el of list) {
      if (el) observer.observe(el);
    }

    return () => observer.disconnect();
  }, [count, refs]);

  return activeIdx;
}
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm test -- useMostVisibleIndex`
Expected: PASS — 3 passing tests.

**Step 5: Commit**

```bash
git add frontend/src/hooks/useMostVisibleIndex.ts frontend/src/hooks/useMostVisibleIndex.test.tsx
git commit -m "feat(feed): add useMostVisibleIndex hook backed by IntersectionObserver"
```

---

## Milestone 2: Wire active-state into cards

**Goal:** `SegmentCard` plays only when its `active` prop is true; `FeedShell` derives `active` from the new hook.

**Acceptance test:** Build (`pnpm build`) succeeds; `pnpm test` is green.

### Task 3: Replace `priority` with `active` in `SegmentCard`

**Behavioral check:** A unit test renders `SegmentCard` with a stubbed `HTMLMediaElement.prototype.play`/`pause`. Toggling `active` from false → true calls `play()`. Toggling true → false calls `pause()`.

**Files:**
- Modify: `frontend/src/components/SegmentCard.tsx` (full file rewrite below)
- Create: `frontend/src/components/SegmentCard.test.tsx`

**Step 1: Write the failing test**

Create `frontend/src/components/SegmentCard.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import { SegmentCard } from "./SegmentCard";
import type { Segment } from "../types";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const playMock = vi.fn(() => Promise.resolve());
const pauseMock = vi.fn();

beforeEach(() => {
  playMock.mockClear();
  pauseMock.mockClear();
  // jsdom doesn't implement these — stub them.
  Object.defineProperty(HTMLMediaElement.prototype, "play", {
    configurable: true,
    value: playMock,
  });
  Object.defineProperty(HTMLMediaElement.prototype, "pause", {
    configurable: true,
    value: pauseMock,
  });
});

let mounted: { container: HTMLDivElement; root: Root }[] = [];

afterEach(() => {
  mounted.forEach(({ root, container }) => {
    act(() => root.unmount());
    container.remove();
  });
  mounted = [];
});

const segment: Segment & { url: string } = {
  id: "seg-1",
  caption: "Test caption",
  source_count: 1,
  created_at: new Date().toISOString(),
  centroid_lat: null,
  centroid_lng: null,
  location: "Pasadena",
  url: "/media/test.mp4",
  video_urls: ["/media/test.mp4"],
} as unknown as Segment & { url: string };

function render(active: boolean) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(<SegmentCard segment={segment} active={active} />);
  });
  mounted.push({ container, root });
  return { container, root };
}

describe("SegmentCard active playback", () => {
  it("calls play() when active=true on mount", () => {
    render(true);
    expect(playMock).toHaveBeenCalled();
    expect(pauseMock).not.toHaveBeenCalled();
  });

  it("calls pause() when active=false on mount", () => {
    render(false);
    expect(pauseMock).toHaveBeenCalled();
    expect(playMock).not.toHaveBeenCalled();
  });

  it("transitions: pauses when active flips true→false", () => {
    const { root } = render(true);
    expect(playMock).toHaveBeenCalledTimes(1);

    act(() => {
      root.render(<SegmentCard segment={segment} active={false} />);
    });
    expect(pauseMock).toHaveBeenCalled();
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test -- SegmentCard`
Expected: FAIL — `active` prop is not yet defined on `SegmentCard` (TS error or behavior mismatch).

**Step 3: Rewrite `SegmentCard` to use `active`**

Replace the full contents of `frontend/src/components/SegmentCard.tsx` with:

```tsx
import { useState, useCallback, useEffect, useRef } from "react";
import type { Segment } from "../types";
import { relativeTime } from "../timeFormat";
import { distanceLabel } from "../distance";
import { LivePill } from "./LivePill";

function deriveSummary(s: Segment, locationStr: string | null): string {
  const angles = s.source_count > 1 ? `Captured from ${s.source_count} angles` : "Single-angle footage";
  const where = locationStr ? ` near ${locationStr}` : "";
  return `${angles}${where}, ${relativeTime(s.created_at)}.`;
}

export function SegmentCard({
  segment,
  viewerLat,
  viewerLng,
  active = false,
}: {
  segment: Segment & { url: string };
  viewerLat?: number;
  viewerLng?: number;
  /** True when this card is the most-visible one in the viewport. */
  active?: boolean;
}) {
  const urls = segment.video_urls?.filter(Boolean) as string[] | undefined;
  const hasMultiple = urls && urls.length > 1;
  const [angleIdx, setAngleIdx] = useState(0);
  const currentUrl = hasMultiple ? urls[angleIdx] : segment.url;
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const handleEnded = useCallback(() => {
    if (!hasMultiple) return;
    setAngleIdx((i) => (i + 1) % urls.length);
  }, [hasMultiple, urls]);

  // Drive playback from the `active` prop. iOS Safari rejects play()
  // without a user gesture in some states — swallow the rejection.
  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    if (active) {
      const p = el.play();
      if (p && typeof p.catch === "function") p.catch(() => {});
    } else {
      el.pause();
    }
  }, [active, currentUrl]);

  const locationStr =
    viewerLat !== undefined &&
    viewerLng !== undefined &&
    segment.centroid_lat !== null &&
    segment.centroid_lng !== null
      ? distanceLabel(viewerLat, viewerLng, segment.centroid_lat, segment.centroid_lng)
      : segment.location;

  const summary = deriveSummary(segment, locationStr ?? null);

  return (
    <article className="relative">
      <div className="relative overflow-hidden rounded-2xl bg-surface aspect-[4/5]">
        <video
          ref={videoRef}
          key={currentUrl}
          src={currentUrl}
          muted
          playsInline
          preload={active ? "auto" : "metadata"}
          onEnded={handleEnded}
          className="absolute inset-0 w-full h-full object-cover"
        />

        <div
          aria-hidden
          className="absolute inset-x-0 top-0 h-1/3 pointer-events-none"
          style={{
            background:
              "linear-gradient(to bottom, rgba(0,0,0,0.65) 0%, rgba(0,0,0,0) 100%)",
          }}
        />

        <div
          aria-hidden
          className="absolute inset-x-0 bottom-0 h-1/2 pointer-events-none"
          style={{ background: "var(--gradient-fade-bottom)" }}
        />

        {hasMultiple && (
          <>
            <button
              type="button"
              onClick={() =>
                setAngleIdx((i) => (i - 1 + urls.length) % urls.length)
              }
              aria-label="Previous angle"
              className="absolute top-0 bottom-0 left-0 w-1/2 z-[5]"
            />
            <button
              type="button"
              onClick={() => setAngleIdx((i) => (i + 1) % urls.length)}
              aria-label="Next angle"
              className="absolute top-0 bottom-0 right-0 w-1/2 z-[5]"
            />

            <div className="absolute top-3 left-3 right-3 z-10 flex gap-1.5 pointer-events-none">
              {urls.map((_, i) => (
                <span
                  key={i}
                  className={`flex-1 h-[3px] rounded-full transition-colors ${
                    i === angleIdx ? "bg-white/75" : "bg-white/30"
                  }`}
                />
              ))}
            </div>
          </>
        )}

        <div className="absolute bottom-3 dark:bottom-14 left-4 z-10">
          <LivePill />
        </div>
      </div>

      <h2
        className="relative z-20 mt-3 dark:-mt-8 dark:sm:-mt-10 px-4 font-display uppercase text-[40px] sm:text-[48px] leading-[0.92] tracking-[-0.005em] text-ink-primary"
      >
        {segment.caption}
      </h2>

      <p className="mt-3 text-[13px] font-semibold leading-[1.35] px-4 bg-gradient-to-r from-coral-light to-coral bg-clip-text text-transparent">
        {summary}
      </p>

      <p className="mt-3 px-4 text-[13px] leading-[1.5] text-ink-primary">
        Two contributors uploaded footage from adjacent vantage points within a 90-second window.
        Visual and audio analysis confirms a shared scene; angles complement rather than duplicate.
        No vehicles or additional bystanders detected. Compiled into a single segment with
        temporal alignment across sources.
      </p>
    </article>
  );
}
```

Key diffs vs. the old file:
- Replaced `priority?: boolean` with `active?: boolean`.
- Removed `autoPlay={priority}` from `<video>`. Playback is now driven by the new `useEffect`.
- Added `videoRef` and `useEffect([active, currentUrl])` calling `play()` / `pause()`.
- `preload` keys off `active` instead of `priority`.

**Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm test -- SegmentCard`
Expected: PASS — 3 passing tests.

Run: `cd frontend && pnpm test`
Expected: full suite green (existing `RecordButton` + `mimeLadder` + new tests).

**Step 5: Commit**

```bash
git add frontend/src/components/SegmentCard.tsx frontend/src/components/SegmentCard.test.tsx
git commit -m "feat(feed): drive SegmentCard playback from active prop"
```

---

### Task 4: Wire hook into `FeedShell`

**Behavioral check:** `pnpm build` succeeds. Manual: in dev, exactly one card has its video playing; scrolling causes a different card to take over.

**Files:**
- Modify: `frontend/src/components/FeedShell.tsx` (full rewrite below)

**Step 1: Write the failing check (build/type)**

After the Task 3 rewrite, `FeedShell.tsx` still passes `priority={i === 0}` to `SegmentCard`, but `SegmentCard` no longer accepts that prop.

Run: `cd frontend && pnpm build`
Expected: FAIL — TypeScript error `Property 'priority' does not exist on type ...`.

**Step 2: Rewrite `FeedShell`**

Replace the full contents of `frontend/src/components/FeedShell.tsx` with:

```tsx
import { useRef } from "react";
import type { Segment } from "../types";
import { SegmentCard } from "./SegmentCard";
import { useMostVisibleIndex } from "../hooks/useMostVisibleIndex";

export function FeedShell({
  segments,
  viewerLat,
  viewerLng,
}: {
  segments: (Segment & { url: string })[];
  viewerLat?: number;
  viewerLng?: number;
}) {
  const itemRefs = useRef<(HTMLLIElement | null)[]>([]);
  const activeIdx = useMostVisibleIndex(itemRefs, segments.length);
  // Until the observer reports anything, default to the top card so the
  // feed isn't silent on first paint.
  const resolvedActive = activeIdx === -1 ? 0 : activeIdx;

  return (
    <main
      className="mx-auto max-w-[640px] px-5 pt-5"
      style={{ paddingBottom: "calc(80px + env(safe-area-inset-bottom))" }}
    >
      <ol className="space-y-10">
        {segments.map((s, i) => (
          <li
            key={s.id}
            ref={(el) => {
              itemRefs.current[i] = el;
            }}
          >
            <SegmentCard
              segment={s}
              viewerLat={viewerLat}
              viewerLng={viewerLng}
              active={i === resolvedActive}
            />
          </li>
        ))}
      </ol>
    </main>
  );
}
```

Key diffs vs. the old file:
- Added `itemRefs` and `useMostVisibleIndex` call.
- Each `<li>` gets a ref so the observer can watch it.
- `priority={i === 0}` → `active={i === resolvedActive}`.
- `-1` is coerced to `0` so we still play the top card at first paint (matches today's behavior before any scrolling).

**Step 3: Run build + tests**

Run: `cd frontend && pnpm build`
Expected: PASS — clean compile.

Run: `cd frontend && pnpm test`
Expected: PASS — full suite green.

**Step 4: Manual smoke test in dev (desktop, before iPhone gate)**

Run: `cd frontend && pnpm dev`
Open in Chrome on desktop. Use device toolbar at iPhone 14 width.
Expected:
- Initial load: top card video plays.
- Scroll the second card into the center: video #2 starts playing, #1 pauses.
- Scroll back to #1: it resumes (or restarts — either is acceptable for the demo).

**Step 5: Commit**

```bash
git add frontend/src/components/FeedShell.tsx
git commit -m "feat(feed): play whichever segment card is most visible in the viewport"
```

---

## Milestone 3: iPhone Safari verification

**Goal:** Confirm on a real iPhone (per CLAUDE.md hard constraint) that the active-on-scroll behavior works without playback stalls.

**Acceptance test:** On a real iPhone, with backend running and at least 3 segments in the feed, scrolling visibly transfers playback to the centered card. No console errors. No stuck-loading spinners.

### Task 5: Real-iPhone smoke test

**Behavioral check:** Documented below — three observations on a real device.

**Steps:**

1. Start backend: `make backend` (or whatever the demo make target is — see `Makefile`).
2. Start frontend on LAN: `cd frontend && pnpm dev` (already runs with `--host`, see `package.json:7`).
3. Open the printed `http://<lan-ip>:5173` URL on iPhone Safari.
4. Ensure ≥ 3 segments are in the feed (record a few clips if needed via the existing `/record` flow).
5. Observe:
   - **Card 1 plays on load.** ✅
   - **Scroll so card 2 is most visible — it starts playing, card 1 pauses.** ✅
   - **Scroll back — playback transfers back.** ✅
6. If anything is broken, capture: which card was visible, Safari console (Settings → Safari → Advanced → Web Inspector via Mac), and note in this plan's "Unresolved questions" section.

**No commit** — this task is observational only.

---

## Unresolved questions

- Should a card scrolled fully off-screen reset to `currentTime = 0`? Plan defers this — pause-only matches TikTok feel and is simpler. Revisit only if QA flags weird "ghost progress bar" state on long clips.
- `rootMargin` is unset, so masthead/tab-bar overlap counts toward intersection. Demo cards are tall enough that the centered one always wins. If it ever picks the wrong card on small screens, tighten with `rootMargin: "-52px 0px -80px 0px"` (masthead 52px, tabbar 80px).
- `IntersectionObserver` is supported on iOS Safari 12.2+. Demo iPhones are fine. Hook short-circuits when undefined → top card plays as fallback.
- Angle-cycling (`onEnded` → `setAngleIdx`) only fires while a video plays. Inactive cards therefore won't cycle in the background. Acceptable: the user is watching the active one anyway.

---

## Progress
- [x] Task 1: pickMaxRatioIndex helper — `a19145b`
- [x] Task 2: useMostVisibleIndex hook — `39c46c1`
- [x] Task 3: SegmentCard active prop — `9964976` (see Surprises)
- [ ] Task 4: FeedShell wires hook ← current
- [ ] Task 5: Real-iPhone smoke test

## Surprises & Discoveries
- Task 3: While I was running tests post-Write, an external process committed our `SegmentCard.tsx` + `SegmentCard.test.tsx` changes alongside unrelated backend scaffolding (`backend/pipeline/runs.py`, `backend/tests/test_runs.py`) in commit `9964976` with the misleading message "scaffold runs module + failing import test". My subsequent `git commit` reported "no changes to commit" because the files were already in the surprise commit. User opted to leave it and continue. SegmentCard test suite passes (3/3) and full suite is green (25/25).

## Execution Handoff

Plan saved to `docs/plans/2026-04-26-active-video-on-scroll.md`. Execution options:

1. **Execute now** — I'll work through tasks in batches with review checkpoints (uses `workflow/executing-plans` methodology).
2. **Execute in new session** — Open new session and run `/execute-plan`. Better for keeping context fresh.
3. **Manual** — You execute the plan yourself.

Which approach?
