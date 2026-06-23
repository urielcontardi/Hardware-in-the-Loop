export interface TierMeta { tier: number; bucketSec: number; }

export function attachStartsPlotSession(state: string): boolean {
  return state === "running";
}

// A historical response stays usable as long as it overlaps the visible window
// at all and has samples — render the portion it covers (viewToProjected clips
// to the window) rather than discarding it. Requiring it to reach the left edge
// blanked the plot whenever a pan moved the window left of the stale response's
// start, until the refetch landed; this keeps the overlapping data visible.
export function viewportIntersects(
  responseFrom: number, responseTo: number,
  visibleFrom: number, visibleTo: number, sampleCount: number,
): boolean {
  return sampleCount > 0
    && responseFrom <= visibleTo + 1e-9
    && responseTo >= visibleFrom - 1e-9;
}

// selectTier mirrors pyramid.SelectTier: coarsest tier whose bucket <= secPerPx,
// or -1 when even the finest tier is coarser than the zoom (use raw T0).
export function selectTier(tiers: TierMeta[], secPerPx: number): number {
  let best = -1;
  for (const t of tiers) {
    if (t.bucketSec <= secPerPx) best = t.tier;
  }
  return best;
}

export type HistoricalSource =
  | { kind: "raw" }
  | { kind: "tier"; tier: number }
  | { kind: "none" };

// Fine, bounded windows come from the disk-backed full-rate store. Wider
// windows use the pyramid; if pixel density asks for more than T1 can provide
// but the raw request would be too large, T1 remains the honest fallback.
export function selectHistoricalSource(
  tiers: TierMeta[], secPerPx: number, windowSec: number, maxRawSec: number,
): HistoricalSource {
  const tier = selectTier(tiers, secPerPx);
  if (tier >= 0) return { kind: "tier", tier };
  if (windowSec <= maxRawSec) return { kind: "raw" };
  return tiers.length > 0 ? { kind: "tier", tier: tiers[0].tier } : { kind: "none" };
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
type Window = [number, number, number];

function sameWindow(a: Window | null, b: Window): boolean {
  return a !== null && a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
}

// ViewportController debounces zoom/pan into a single query and only delivers a
// response if its window is still the current one (kills the stale-range race).
// The optional `generation` provider additionally drops responses that were
// issued before a session reset (Connect/clear bumps streamGeneration): an
// in-flight /api/view request fetches the gateway's previous-run data, and
// without this guard it would paint stale history into the fresh session.
export class ViewportController<T = unknown> {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pending: Window | null = null;
  private inFlight: Window | null = null;
  onData: (data: T) => void = () => {};

  constructor(
    private fetcher: Fetcher<T>,
    private debounceMs = 60,
    private generation?: () => number,
  ) {}

  request(from: number, to: number, width: number): void {
    const next: Window = [from, to, width];
    // Ignore a repeat of the window already pending or in flight. The history
    // poller re-issues the same window every tick; bumping seq here would
    // discard the in-flight response (seq guard below), and when the fetch is
    // slower than the poll interval (wide zoom-out tiles) it would never land.
    if (sameWindow(this.pending, next) || sameWindow(this.inFlight, next)) return;
    this.pending = next;
    // Keep at most one request in flight. Live-window updates replace the
    // pending window; after the response lands, fetch only the newest one.
    if (this.inFlight) return;
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush(), this.debounceMs);
  }

  private async flush(): Promise<void> {
    this.timer = null;
    if (this.inFlight || !this.pending) return;
    const win = this.pending;
    this.pending = null;
    this.inFlight = win;
    const gen = this.generation?.();
    try {
      const data = await this.fetcher(win[0], win[1], win[2]);
      if (this.generation && gen !== this.generation()) return; // session reset superseded this window
      this.onData(data);
    } finally {
      this.inFlight = null;
      if (this.pending) this.timer = setTimeout(() => this.flush(), 0);
    }
  }
}
