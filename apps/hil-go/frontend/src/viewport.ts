import type { SeriesColumns } from "./series";

type Fetcher = (from: number, to: number, width: number) => Promise<SeriesColumns>;

// ViewportController debounces zoom/pan into a single query for the latest
// visible range, and hands the result to onData.
export class ViewportController {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pending: [number, number, number] | null = null;
  private seq = 0;
  onData: (cols: SeriesColumns) => void = () => {};

  constructor(private fetcher: Fetcher, private debounceMs = 60) {}

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
    const cols = await this.fetcher(from, to, width);
    if (seq !== this.seq) return;
    this.onData(cols);
  }
}
