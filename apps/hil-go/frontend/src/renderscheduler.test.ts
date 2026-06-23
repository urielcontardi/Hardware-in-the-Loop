import { describe, it, expect, vi } from "vitest";
import { RenderScheduler } from "./renderscheduler";

// Deterministic stand-ins for setTimeout / requestAnimationFrame / clock so we
// can drive the scheduler frame-by-frame and, crucially, simulate a hidden tab
// by withholding the animation-frame callbacks.
function manualEnv() {
  let t = 0;
  const timers: Array<() => void> = [];
  const frames: Array<() => void> = [];
  return {
    now: () => t,
    setTimer: (fn: () => void) => { timers.push(fn); },
    requestFrame: (fn: () => void) => { frames.push(fn); },
    advance: (ms: number) => { t += ms; },
    runTimers: () => { timers.splice(0).forEach((f) => f()); },
    runFrames: () => { frames.splice(0).forEach((f) => f()); },
    pendingTimers: () => timers.length,
    pendingFrames: () => frames.length,
  };
}

describe("RenderScheduler", () => {
  it("coalesces a burst of requests into a single render", () => {
    const env = manualEnv();
    const render = vi.fn();
    const rs = new RenderScheduler(render, env);

    rs.request(); rs.request(); rs.request();
    env.runTimers();
    env.runFrames();

    expect(render).toHaveBeenCalledTimes(1);
  });

  // Regression: requestAnimationFrame is paused while the tab is hidden. If the
  // coalescing guard were only released inside the frame callback, a frame
  // deferred by a hidden tab would strand the guard and silently drop every
  // later request — the "I have to switch tabs and come back to see the wave"
  // bug. The guard must release when the interval timer fires, so new requests
  // keep scheduling even while frames are withheld.
  it("does not strand future renders when a frame is deferred (hidden tab)", () => {
    const env = manualEnv();
    const render = vi.fn();
    const rs = new RenderScheduler(render, env);

    rs.request();
    env.runTimers();                 // interval elapses, a frame is requested...
    // tab hidden: do NOT run frames — the frame callback never fires.
    expect(env.pendingFrames()).toBe(1);

    rs.request();                    // new state while hidden
    expect(env.pendingTimers()).toBe(1); // must schedule again, not be dropped
  });

  it("flush() forces an immediate render when the tab regains visibility", () => {
    const env = manualEnv();
    const render = vi.fn();
    const rs = new RenderScheduler(render, env);

    rs.request();
    env.runTimers();                 // frame requested but tab hidden, not painted
    expect(render).not.toHaveBeenCalled();

    rs.flush();                      // visibilitychange -> visible
    expect(render).toHaveBeenCalledTimes(1);

    // and the pipeline keeps scheduling new work afterwards
    rs.request();
    expect(env.pendingTimers()).toBe(1);
  });
});
