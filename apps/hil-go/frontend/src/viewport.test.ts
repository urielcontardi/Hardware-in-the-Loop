import { describe, it, expect, vi } from "vitest";
import { ViewportController, attachStartsPlotSession, indicesForWindow, selectHistoricalSource, selectTier, viewportIntersects } from "./viewport";

describe("plot session lifecycle", () => {
  it("keeps Connect blank unless the board is already running", () => {
    expect(attachStartsPlotSession("paused")).toBe(false);
    expect(attachStartsPlotSession("stopped")).toBe(false);
    expect(attachStartsPlotSession("running")).toBe(true);
  });
});

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

  it("uses full-rate history only for bounded fine windows", () => {
    expect(selectHistoricalSource(tiers, 0.00001, 0.06, 2)).toEqual({ kind: "raw" });
    expect(selectHistoricalSource(tiers, 0.002, 0.06, 2)).toEqual({ kind: "tier", tier: 0 });
    expect(selectHistoricalSource(tiers, 0.00001, 3, 2)).toEqual({ kind: "tier", tier: 0 });
  });
});

describe("indicesForWindow", () => {
  it("maps a time window to tile indices", () => {
    // bucketSec 0.001, 1024 buckets/tile => tile covers 1.024 s.
    expect(indicesForWindow(0.001, 1024, 0.0, 2.0)).toEqual([0, 1]);
    expect(indicesForWindow(0.001, 1024, 1.1, 1.2)).toEqual([1]);
  });
});

describe("historical viewport usability", () => {
  // Window [visFrom, visTo]; response covers [respFrom, respTo].
  it("accepts a response that trails the live right edge", () => {
    expect(viewportIntersects(10, 10.9, 10.2, 11, 100)).toBe(true);
  });

  // Regression: panning left moves the window's left edge before the stale
  // response's start. The response still overlaps the right portion of the
  // window, so its data must stay visible (clipped) instead of the plot going
  // blank until the refetch lands.
  it("keeps a response that overlaps only the right part of a panned window", () => {
    expect(viewportIntersects(0.2, 0.7, 0, 0.5, 100)).toBe(true);
  });

  it("rejects empty and non-overlapping responses", () => {
    expect(viewportIntersects(10, 11, 10.2, 11, 0)).toBe(false);   // no samples
    expect(viewportIntersects(0.6, 0.9, 0, 0.5, 100)).toBe(false); // entirely right of window
    expect(viewportIntersects(9, 9.8, 10.2, 11, 100)).toBe(false); // entirely left of window
  });
});

describe("ViewportController", () => {
  it("finishes the in-flight window and then fetches the newest pending window", async () => {
    let resolveFirst: (v: number[]) => void = () => {};
    const onData = vi.fn();
    const ctl = new ViewportController(async (from) => {
      if (from === 0) return new Promise<number[]>((r) => { resolveFirst = r; });
      return [from];
    }, 0);
    ctl.onData = onData;

    ctl.request(0, 1, 800);
    await new Promise((r) => setTimeout(r));
    ctl.request(2, 3, 800);
    ctl.request(5, 6, 800);
    resolveFirst([0]);
    await new Promise((r) => setTimeout(r));
    await new Promise((r) => setTimeout(r));

    expect(onData.mock.calls.map(c => c[0])).toEqual([[0], [5]]);
  });

  // Regression: the history poller re-issues the SAME window every ~100ms. At
  // wide zoom-out the tile is large (~15k buckets) and the fetch outlasts the
  // poll interval, so each response was superseded by the next identical
  // request before it resolved — latestHistorical never updated and the view
  // stayed stuck on stale/partial data. A repeat of the in-flight window must
  // be ignored so the outstanding fetch is allowed to complete.
  it("lets an in-flight response complete when the same window is re-requested", async () => {
    let resolveInflight: (v: number[]) => void = () => {};
    let fetchCount = 0;
    const onData = vi.fn();
    const ctl = new ViewportController<number[]>((from) => {
      fetchCount++;
      return new Promise<number[]>((r) => { resolveInflight = r; });
    }, 0);
    ctl.onData = onData;

    ctl.request(0, 15, 1400);
    await new Promise((r) => setTimeout(r));   // debounce flush -> fetch in flight
    expect(fetchCount).toBe(1);

    ctl.request(0, 15, 1400);                  // poller re-tick, identical window
    await new Promise((r) => setTimeout(r));
    expect(fetchCount).toBe(1);                // no second fetch started

    resolveInflight([7]);                      // the slow wide response finally lands
    await Promise.resolve(); await Promise.resolve();
    expect(onData).toHaveBeenCalledWith([7]);  // and is delivered, not discarded
  });

  // Connect/clear bumps the session generation while a viewport request may be
  // in flight against the gateway's previous-run data. That response must be
  // dropped so stale history never paints into the fresh session's plots.
  it("discards a response issued before a session reset (connect/clear)", async () => {
    let resolveInflight: (v: number[]) => void = () => {};
    const onData = vi.fn();
    let generation = 0;
    const ctl = new ViewportController(
      async () => new Promise<number[]>((r) => { resolveInflight = r; }),
      0,
      () => generation,
    );
    ctl.onData = onData;

    ctl.request(0, 1, 800);                       // fired against the previous session
    await new Promise((r) => setTimeout(r));      // debounce flushes → request in flight
    generation++;                                 // Connect → resetPlotBuffer bumps streamGeneration
    resolveInflight([42]);                        // stale gateway data resolves after the reset
    await Promise.resolve(); await Promise.resolve();

    expect(onData).not.toHaveBeenCalled();
  });

  it("delivers a response when the session generation is unchanged", async () => {
    const onData = vi.fn();
    const ctl = new ViewportController(async (from) => [from], 0, () => 7);
    ctl.onData = onData;

    ctl.request(3, 4, 800);
    await new Promise((r) => setTimeout(r));      // debounce flushes
    await Promise.resolve();

    expect(onData).toHaveBeenCalledWith([3]);
  });
});
