// Channel order MUST match derive.Channels in the gateway.
export const CHANNEL_NAMES = [
  "Ia", "Ib", "Ic", "FluxA", "FluxB", "FluxC", "Speed", "Te",
] as const;
export const NUM_CH = CHANNEL_NAMES.length;

export interface SeriesColumns {
  t: number[];
  min: number[][]; // [channel][column]
  max: number[][];
  mean: number[][];
}

export function decodeSeries(buf: ArrayBuffer): SeriesColumns {
  const dv = new DataView(buf);
  const count = dv.getUint32(0, true);
  const nch = dv.getUint8(4);
  const t: number[] = new Array(count);
  const min: number[][] = Array.from({ length: nch }, () => new Array(count));
  const max: number[][] = Array.from({ length: nch }, () => new Array(count));
  const mean: number[][] = Array.from({ length: nch }, () => new Array(count));
  const perCh = buf.byteLength === 5 + count * (4 + nch * 12) ? 12 : 8;
  let off = 5;
  for (let i = 0; i < count; i++) {
    t[i] = dv.getFloat32(off, true); off += 4;
    for (let ch = 0; ch < nch; ch++) {
      min[ch][i] = dv.getFloat32(off, true);
      max[ch][i] = dv.getFloat32(off + 4, true);
      mean[ch][i] = perCh === 12 ? dv.getFloat32(off + 8, true) : (min[ch][i] + max[ch][i]) / 2;
      off += perCh;
    }
  }
  return { t, min, max, mean };
}

export async function fetchSeries(
  from: number, to: number, width: number,
): Promise<SeriesColumns> {
  const url = `/api/series?from=${from}&to=${to}&width=${Math.round(width)}`;
  const res = await fetch(url, { cache: "no-store" });
  return decodeSeries(await res.arrayBuffer());
}
