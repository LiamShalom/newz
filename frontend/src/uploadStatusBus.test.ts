import { describe, it, expect, beforeEach } from "vitest";
import {
  getUploadStatus,
  setUploadStatus,
  subscribeToUploadStatus,
} from "./uploadStatusBus";

// Module-level singleton: each test resets to idle in beforeEach.

describe("uploadStatusBus", () => {
  beforeEach(() => {
    setUploadStatus({ kind: "idle" });
  });

  it("starts (after reset) as idle", () => {
    expect(getUploadStatus()).toEqual({ kind: "idle" });
  });

  it("set→subscribe→read flow fires once on transition", () => {
    let calls = 0;
    const unsub = subscribeToUploadStatus(() => {
      calls += 1;
    });

    setUploadStatus({ kind: "uploading" });
    expect(getUploadStatus()).toEqual({ kind: "uploading" });
    expect(calls).toBe(1);

    unsub();
  });

  it("setting same kind twice in a row does not re-dispatch", () => {
    let calls = 0;
    const unsub = subscribeToUploadStatus(() => {
      calls += 1;
    });

    setUploadStatus({ kind: "uploading" });
    setUploadStatus({ kind: "uploading" });
    expect(calls).toBe(1);

    unsub();
  });

  it("error state with the same message does not re-dispatch", () => {
    let calls = 0;
    const unsub = subscribeToUploadStatus(() => {
      calls += 1;
    });

    setUploadStatus({ kind: "error", message: "Upload failed" });
    setUploadStatus({ kind: "error", message: "Upload failed" });
    expect(calls).toBe(1);
    // Different message DOES re-dispatch.
    setUploadStatus({ kind: "error", message: "Upload queued — will retry" });
    expect(calls).toBe(2);

    unsub();
  });

  it("idle reset after error fires the listener and clears state", () => {
    let calls = 0;
    const unsub = subscribeToUploadStatus(() => {
      calls += 1;
    });

    setUploadStatus({ kind: "error", message: "Upload failed" });
    expect(getUploadStatus()).toEqual({
      kind: "error",
      message: "Upload failed",
    });
    setUploadStatus({ kind: "idle" });
    expect(getUploadStatus()).toEqual({ kind: "idle" });
    expect(calls).toBe(2);

    unsub();
  });

  it("subscribe returns an unsubscribe that actually unsubscribes", () => {
    let calls = 0;
    const unsub = subscribeToUploadStatus(() => {
      calls += 1;
    });

    setUploadStatus({ kind: "uploading" });
    expect(calls).toBe(1);
    unsub();
    setUploadStatus({ kind: "idle" });
    expect(calls).toBe(1); // listener removed before second dispatch
  });
});
