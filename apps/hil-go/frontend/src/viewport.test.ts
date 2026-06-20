import { describe, it, expect } from "vitest";
import { ViewportController } from "./viewport";

describe("ViewportController", () => {
  it("debounces and queries once with latest range", async () => {
    const calls: Array<[number, number, number]> = [];
    const vc = new ViewportController(
      async (from, to, w) => { calls.push([from, to, w]); return { t: [], min: [], max: [] }; },
      10,
    );
    vc.request(0, 1, 800);
    vc.request(0.5, 1.5, 800);
    await new Promise((r) => setTimeout(r, 30));
    expect(calls.length).toBe(1);
    expect(calls[0][0]).toBeCloseTo(0.5);
    expect(calls[0][1]).toBeCloseTo(1.5);
  });

  it("ignores stale responses after a newer request", async () => {
    const delivered: number[] = [];
    const resolvers: Array<(value: { t: number[]; min: number[][]; max: number[][] }) => void> = [];
    const vc = new ViewportController(
      async (from) => new Promise(resolve => { resolvers.push(resolve); }),
      1,
    );
    vc.onData = (cols) => { delivered.push(cols.t[0]); };

    vc.request(0, 1, 800);
    await new Promise((r) => setTimeout(r, 5));
    vc.request(1, 2, 800);
    resolvers[0]({ t: [0], min: [], max: [] });
    await new Promise((r) => setTimeout(r, 5));
    expect(delivered).toEqual([]);

    resolvers[1]({ t: [1], min: [], max: [] });
    await new Promise((r) => setTimeout(r, 5));
    expect(delivered).toEqual([1]);
  });
});
