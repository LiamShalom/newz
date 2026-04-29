import { describe, it, expect } from "vitest";
import { _abs, API_BASE } from "./api";

describe("_abs guard (BLOB-05)", () => {
  it("prefixes API_BASE for relative paths", () => {
    expect(_abs("/media/x.mp4")).toBe(`${API_BASE}/media/x.mp4`);
  });

  it("returns absolute https URLs unchanged", () => {
    const url = "https://store.public.blob.vercel-storage.com/runs/x.mp4";
    expect(_abs(url)).toBe(url);
  });

  it("returns null for null input", () => {
    expect(_abs(null)).toBeNull();
  });

  it("returns null for undefined input", () => {
    expect(_abs(undefined)).toBeNull();
  });
});
