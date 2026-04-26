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
