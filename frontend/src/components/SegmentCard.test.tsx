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

const segment: Segment & { url: string | null } = {
  id: "seg-1",
  cluster_id: "cluster-1",
  ordered_clip_ids: ["clip-1"],
  title: "Test Title",
  caption: "Test caption",
  location: "Pasadena, CA",
  source_count: 1,
  created_at: Math.floor(Date.now() / 1000),
  centroid_lat: null,
  centroid_lng: null,
  video_url: "/media/test.mp4",
  video_urls: ["/media/test.mp4"],
  soft_flag: false,
  url: "/media/test.mp4",
};

// Phase 10 (BLOB-05): same fixture with absolute Blob URLs to assert no
// double-prefix in render.
const blobSegment: Segment & { url: string | null } = {
  ...segment,
  video_url: "https://teststore.public.blob.vercel-storage.com/runs/seg-1.mp4",
  video_urls: ["https://teststore.public.blob.vercel-storage.com/runs/seg-1.mp4"],
  url: "https://teststore.public.blob.vercel-storage.com/runs/seg-1.mp4",
};

function render(active: boolean, seg: Segment & { url: string | null } = segment) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(<SegmentCard segment={seg} active={active} />);
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

  it.each([
    ["relative", segment],
    ["absolute Blob URL", blobSegment],
  ])("renders %s without double-prefix", (_label, seg) => {
    const { container } = render(true, seg);
    const video = container.querySelector("video");
    if (video && seg.url) {
      const src = video.getAttribute("src") ?? video.querySelector("source")?.getAttribute("src");
      if (src) {
        // No double-prefix: src must NOT contain "httphttps" or two http schemes.
        expect(src).not.toMatch(/http.*http/);
      }
    }
  });
});
