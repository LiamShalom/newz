import { describe, it, expect, beforeEach, vi } from "vitest";
import { getPositionWithTimeout } from "./getPositionWithTimeout";

function mockGeo(
  impl: (success: PositionCallback, error: PositionErrorCallback) => void,
) {
  (globalThis as any).navigator = {
    geolocation: { getCurrentPosition: vi.fn().mockImplementation(impl) },
  };
}

describe("getPositionWithTimeout", () => {
  beforeEach(() => {
    vi.useRealTimers();
  });

  it("resolves to ok when geolocation succeeds", async () => {
    mockGeo((success) =>
      success({
        coords: { latitude: 34.14, longitude: -118.13 },
      } as GeolocationPosition),
    );
    const r = await getPositionWithTimeout(5000);
    expect(r).toEqual({ kind: "ok", lat: 34.14, lng: -118.13 });
  });

  it("resolves to denied on PERMISSION_DENIED", async () => {
    mockGeo((_s, error) =>
      error({ code: 1, message: "denied" } as GeolocationPositionError),
    );
    expect(await getPositionWithTimeout(5000)).toEqual({ kind: "denied" });
  });

  it("resolves to unavailable on POSITION_UNAVAILABLE", async () => {
    mockGeo((_s, error) =>
      error({ code: 2, message: "unavailable" } as GeolocationPositionError),
    );
    expect(await getPositionWithTimeout(5000)).toEqual({ kind: "unavailable" });
  });

  it("resolves to timeout on code 3", async () => {
    mockGeo((_s, error) =>
      error({ code: 3, message: "timeout" } as GeolocationPositionError),
    );
    expect(await getPositionWithTimeout(5000)).toEqual({ kind: "timeout" });
  });

  it("calls getCurrentPosition exactly once", async () => {
    const cb = vi.fn().mockImplementation((success: PositionCallback) =>
      success({
        coords: { latitude: 0, longitude: 0 },
      } as GeolocationPosition),
    );
    (globalThis as any).navigator = {
      geolocation: { getCurrentPosition: cb },
    };
    await getPositionWithTimeout(5000);
    expect(cb).toHaveBeenCalledTimes(1);
  });
});
