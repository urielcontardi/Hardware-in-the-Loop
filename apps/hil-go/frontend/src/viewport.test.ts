import { describe, it, expect, vi } from "vitest";
import { ViewportController, indicesForWindow, selectTier } from "./viewport";

describe("selectTier", () => {
  const tiers = [
    { tier: 0, bucketSec: 0.001 },
    { tier: 1, bucketSec: 0.020 },
    { tier: 2, bucketSec: 0.500 },
    { tier: 3, bucketSec: 10.0 },
  ];
  it("picks the coarsest tier that still gives >=1 bucket/pixel", () => {
    expect(selectTier(tiers, 0.0001)).toBe(-1); // raw
    expect(selectTier(tiers, 0.002)).toBe(0);
    expect(selectTier(tiers, 0.6)).toBe(2);
    expect(selectTier(tiers, 100)).toBe(3);
  });
});

describe("indicesForWindow", () => {
  it("maps a time window to tile indices", () => {
    // bucketSec 0.001, 1024 buckets/tile => tile covers 1.024 s.
    expect(indicesForWindow(0.001, 1024, 0.0, 2.0)).toEqual([0, 1]);
    expect(indicesForWindow(0.001, 1024, 1.1, 1.2)).toEqual([1]);
  });
});

describe("ViewportController", () => {
  it("discards a response whose window is no longer current", async () => {
    let resolveFirst: (v: number[]) => void = () => {};
    const onData = vi.fn();
    const ctl = new ViewportController(async (from) => {
      if (from === 0) return new Promise<number[]>((r) => { resolveFirst = r; });
      return [from];
    }, 0);
    ctl.onData = onData;

    ctl.request(0, 1, 800);     // slow, will resolve late
    ctl.request(5, 6, 800);     // newer window
    await Promise.resolve();
    resolveFirst([0]);          // late response from the stale window
    await Promise.resolve(); await Promise.resolve();

    // onData must only ever be called with the newest window's data.
    for (const call of onData.mock.calls) {
      expect(call[0]).not.toEqual([0]);
    }
  });
});
