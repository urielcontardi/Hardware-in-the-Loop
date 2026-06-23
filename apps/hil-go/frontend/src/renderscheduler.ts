export interface RenderSchedulerEnv {
  now?: () => number;
  setTimer?: (fn: () => void, ms: number) => void;
  requestFrame?: (fn: () => void) => void;
  intervalMs?: number;
}

// Coalesces render requests to at most one paint per interval, then paints in a
// requestAnimationFrame so uPlot updates align with the display.
//
// The subtle part is hidden-tab safety. requestAnimationFrame is paused while
// the document is hidden, so a frame requested just before the tab loses
// visibility never runs. The coalescing guard is therefore released when the
// interval *timer* fires (not inside the frame callback): otherwise a deferred
// frame would strand the guard and every later request() would be dropped,
// freezing the view on stale data until the tab became visible again. `flush()`
// is the explicit "tab is visible again, paint now" entry point.
export class RenderScheduler {
  private coalescing = false;
  private lastRenderAt = 0;
  private readonly now: () => number;
  private readonly setTimer: (fn: () => void, ms: number) => void;
  private readonly requestFrame: (fn: () => void) => void;
  private readonly intervalMs: number;

  constructor(private readonly render: () => void, env: RenderSchedulerEnv = {}) {
    this.now = env.now ?? (() => performance.now());
    this.setTimer = env.setTimer ?? ((fn, ms) => { setTimeout(fn, ms); });
    this.requestFrame = env.requestFrame ?? ((fn) => { requestAnimationFrame(fn); });
    this.intervalMs = env.intervalMs ?? 50;
  }

  request(): void {
    if (this.coalescing) return;
    this.coalescing = true;
    const delay = Math.max(0, this.intervalMs - (this.now() - this.lastRenderAt));
    this.setTimer(() => {
      // Release the guard before requesting the frame so a frame the browser
      // defers (hidden tab) can never block subsequent requests.
      this.coalescing = false;
      this.requestFrame(() => this.paint());
    }, delay);
  }

  // Force an immediate paint regardless of the coalescing window. Wire this to
  // visibilitychange so returning to the tab repaints with current data — the
  // automatic form of the manual "switch tabs and back" recovery.
  flush(): void {
    this.coalescing = false;
    this.paint();
  }

  private paint(): void {
    this.lastRenderAt = this.now();
    this.render();
  }
}
