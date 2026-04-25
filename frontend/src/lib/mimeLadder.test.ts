import { describe, it, expect, beforeEach, vi } from "vitest";
import { MIME_CANDIDATES, pickMimeType } from "./mimeLadder";

describe("MIME_CANDIDATES", () => {
  it("contains the four exact strings in the documented order", () => {
    expect([...MIME_CANDIDATES]).toEqual([
      "video/mp4;codecs=avc1,mp4a",
      "video/webm;codecs=vp9,opus",
      "video/webm;codecs=vp8,opus",
      "video/webm",
    ]);
  });
});

describe("pickMimeType", () => {
  beforeEach(() => {
    // @ts-expect-error - mocking global
    globalThis.MediaRecorder = { isTypeSupported: vi.fn() };
  });

  it("returns the first supported candidate (Safari preference path)", () => {
    (globalThis.MediaRecorder.isTypeSupported as any).mockImplementation(
      (t: string) => t === "video/mp4;codecs=avc1,mp4a",
    );
    expect(pickMimeType()).toBe("video/mp4;codecs=avc1,mp4a");
  });

  it("falls through to plain video/webm when only that is supported", () => {
    (globalThis.MediaRecorder.isTypeSupported as any).mockImplementation(
      (t: string) => t === "video/webm",
    );
    expect(pickMimeType()).toBe("video/webm");
  });

  it("returns undefined when nothing is supported", () => {
    (globalThis.MediaRecorder.isTypeSupported as any).mockReturnValue(false);
    expect(pickMimeType()).toBeUndefined();
  });
});
