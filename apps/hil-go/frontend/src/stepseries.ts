export interface StepPoint { t: number; value: number; }

export function recordStep(points: StepPoint[], t: number, value: number): void {
  if (!Number.isFinite(t) || !Number.isFinite(value)) return;
  const last = points[points.length - 1];
  if (last && Math.abs(last.t - t) < 1e-12) {
    last.value = value;
    return;
  }
  points.push({ t, value });
  if (last && t < last.t) points.sort((a, b) => a.t - b.t);
}

export function stepValueAt(points: StepPoint[], t: number, fallback = 0): number {
  let lo = 0, hi = points.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (points[mid].t <= t) lo = mid + 1; else hi = mid;
  }
  return lo > 0 ? points[lo - 1].value : fallback;
}
