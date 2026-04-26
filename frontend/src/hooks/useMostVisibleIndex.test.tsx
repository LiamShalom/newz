import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createRoot, type Root } from "react-dom/client";
import { act, useRef, useEffect } from "react";
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
