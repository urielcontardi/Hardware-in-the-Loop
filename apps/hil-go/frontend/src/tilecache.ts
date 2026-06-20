import { decodeTile, TileData } from "./tile";

export interface FetchedTile { data: ArrayBuffer; sealed: boolean; }
type TileFetcher = (tier: number, index: number) => Promise<FetchedTile>;

interface Entry { tile: TileData; sealed: boolean; }

// TileCache fetches tiles on demand, keeps sealed ones (LRU-bounded) and always
// refetches the unsealed trailing tile so the live edge stays fresh.
export class TileCache {
  private map = new Map<string, Entry>();
  constructor(
    private fetcher: TileFetcher,
    public bucketsPerTile: number,
    private maxTiles: number,
  ) {}

  private key(tier: number, index: number): string { return `${tier}:${index}`; }

  // ensure guarantees every tile index in `indices` for `tier` is loaded.
  async ensure(tier: number, indices: number[]): Promise<void> {
    await Promise.all(indices.map(async (index) => {
      const k = this.key(tier, index);
      const hit = this.map.get(k);
      if (hit && hit.sealed) { this.touch(k, hit); return; }
      const res = await this.fetcher(tier, index);
      const entry: Entry = { tile: decodeTile(res.data), sealed: res.sealed };
      this.touch(k, entry);
    }));
  }

  // window returns the buckets across `indices` (in order) for rendering.
  window(tier: number, indices: number[]): TileData[] {
    const out: TileData[] = [];
    for (const index of indices) {
      const e = this.map.get(this.key(tier, index));
      if (e) out.push(e.tile);
    }
    return out;
  }

  private touch(k: string, e: Entry): void {
    this.map.delete(k);
    this.map.set(k, e); // re-insert => most recently used
    while (this.map.size > this.maxTiles) {
      const oldest = this.map.keys().next().value as string;
      this.map.delete(oldest);
    }
  }

  clear(): void { this.map.clear(); }
}
