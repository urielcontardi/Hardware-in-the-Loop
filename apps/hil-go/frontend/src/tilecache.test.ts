import { describe, it, expect, vi } from "vitest";
import { TileCache } from "./tilecache";
import { encodeTileForTest, NUM_CH } from "./tile";

function fakeTileBytes(tier: number, index: number): ArrayBuffer {
  // One bucket per tile, value = index, bucketSec 0.001, 1024 buckets/tile.
  const tStart = index * 1024 * 0.001;
  const f = (v: number) => new Array(NUM_CH).fill(v);
  return encodeTileForTest(tier, 0.001, tStart, [
    { tStart, min: f(index), max: f(index), mean: f(index) },
  ]);
}

describe("TileCache", () => {
  it("fetches missing tiles and reuses cached ones on pan", async () => {
    const fetcher = vi.fn(async (tier: number, index: number) => ({
      data: fakeTileBytes(tier, index),
      sealed: true,
    }));
    const cache = new TileCache(fetcher, 1024, 100);

    await cache.ensure(0, [0, 1]);
    expect(fetcher).toHaveBeenCalledTimes(2);

    // Pan that needs tile 1 (cached) and 2 (new): only tile 2 is fetched.
    await cache.ensure(0, [1, 2]);
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("always refetches the unsealed trailing tile", async () => {
    const fetcher = vi.fn(async (tier: number, index: number) => ({
      data: fakeTileBytes(tier, index),
      sealed: false,
    }));
    const cache = new TileCache(fetcher, 1024, 100);
    await cache.ensure(0, [0]);
    await cache.ensure(0, [0]);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
