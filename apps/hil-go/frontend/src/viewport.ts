export interface TierMeta { tier: number; bucketSec: number; }

// selectTier mirrors pyramid.SelectTier: coarsest tier whose bucket <= secPerPx,
// or -1 when even the finest tier is coarser than the zoom (use raw T0).
export function selectTier(tiers: TierMeta[], secPerPx: number): number {
  let best = -1;
  for (const t of tiers) {
    if (t.bucketSec <= secPerPx) best = t.tier;
  }
  return best;
}

// indicesForWindow returns the tile indices covering [from,to] for a tier.
export function indicesForWindow(
  bucketSec: number, bucketsPerTile: number, from: number, to: number,
): number[] {
  const tileSec = bucketSec * bucketsPerTile;
  const first = Math.max(0, Math.floor(from / tileSec));
  const last = Math.max(first, Math.floor(to / tileSec));
  const out: number[] = [];
  for (let i = first; i <= last; i++) out.push(i);
  return out;
}

type Fetcher<T> = (from: number, to: number, width: number) => Promise<T>;

// ViewportController debounces zoom/pan into a single query and only delivers a
// response if its window is still the current one (kills the stale-range race).
export class ViewportController<T = unknown> {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pending: [number, number, number] | null = null;
  private seq = 0;
  onData: (data: T) => void = () => {};

  constructor(private fetcher: Fetcher<T>, private debounceMs = 60) {}

  request(from: number, to: number, width: number): void {
    this.seq++;
    this.pending = [from, to, width];
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush(), this.debounceMs);
  }

  private async flush(): Promise<void> {
    if (!this.pending) return;
    const [from, to, width] = this.pending;
    this.pending = null;
    const seq = this.seq;
    const data = await this.fetcher(from, to, width);
    if (seq !== this.seq) return; // a newer window superseded this one
    this.onData(data);
  }
}
