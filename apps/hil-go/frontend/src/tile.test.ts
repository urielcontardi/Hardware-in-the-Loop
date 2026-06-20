import { describe, it, expect } from "vitest";
import { encodeTileForTest, decodeTile, NUM_CH } from "./tile";

describe("decodeTile", () => {
  it("reads header and buckets", () => {
    const buf = encodeTileForTest(0, 0.001, 0.0, [
      { tStart: 0.0, min: filled(-3), max: filled(5), mean: filled(1) },
      { tStart: 0.001, min: filled(2), max: filled(2), mean: filled(2) },
    ]);
    const tile = decodeTile(buf);
    expect(tile.tier).toBe(0);
    expect(tile.bucketSec).toBeCloseTo(0.001);
    expect(tile.t.length).toBe(2);
    expect(tile.min[0][0]).toBe(-3);
    expect(tile.max[0][0]).toBe(5);
    expect(tile.mean[0][1]).toBe(2);
  });
});

function filled(v: number): number[] {
  return new Array(NUM_CH).fill(v);
}
