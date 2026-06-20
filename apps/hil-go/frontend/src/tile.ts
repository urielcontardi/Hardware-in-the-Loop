// Channel order MUST match derive.Channels in the gateway.
export const CHANNEL_NAMES = [
  "Ia", "Ib", "Ic", "FluxA", "FluxB", "FluxC", "Speed", "Te",
] as const;
export const NUM_CH = CHANNEL_NAMES.length;

export interface TileData {
  tier: number;
  bucketSec: number;
  tStart0: number;
  t: number[];
  min: number[][]; // [channel][bucket]
  max: number[][];
  mean: number[][];
}

const HEADER = 13;
const PER_CH = 12;

// decodeTile parses the wire format produced by pyramid.EncodeTile.
export function decodeTile(buf: ArrayBuffer): TileData {
  const dv = new DataView(buf);
  const tier = dv.getUint8(0);
  const count = dv.getUint16(1, true);
  const nch = dv.getUint8(3);
  const bucketSec = dv.getFloat32(4, true);
  const tStart0 = dv.getFloat32(8, true);
  const t: number[] = new Array(count);
  const min: number[][] = Array.from({ length: nch }, () => new Array(count));
  const max: number[][] = Array.from({ length: nch }, () => new Array(count));
  const mean: number[][] = Array.from({ length: nch }, () => new Array(count));
  let off = HEADER;
  for (let i = 0; i < count; i++) {
    t[i] = dv.getFloat32(off, true); off += 4;
    for (let ch = 0; ch < nch; ch++) {
      min[ch][i] = dv.getFloat32(off, true);
      max[ch][i] = dv.getFloat32(off + 4, true);
      mean[ch][i] = dv.getFloat32(off + 8, true);
      off += PER_CH;
    }
  }
  return { tier, bucketSec, tStart0, t, min, max, mean };
}

// encodeTileForTest mirrors the Go encoder so unit tests have golden input.
export function encodeTileForTest(
  tier: number, bucketSec: number, tStart0: number,
  buckets: { tStart: number; min: number[]; max: number[]; mean: number[] }[],
): ArrayBuffer {
  const rec = 4 + NUM_CH * PER_CH;
  const buf = new ArrayBuffer(HEADER + buckets.length * rec);
  const dv = new DataView(buf);
  dv.setUint8(0, tier);
  dv.setUint16(1, buckets.length, true);
  dv.setUint8(3, NUM_CH);
  dv.setFloat32(4, bucketSec, true);
  dv.setFloat32(8, tStart0, true);
  let off = HEADER;
  for (const b of buckets) {
    dv.setFloat32(off, b.tStart, true); off += 4;
    for (let ch = 0; ch < NUM_CH; ch++) {
      dv.setFloat32(off, b.min[ch], true);
      dv.setFloat32(off + 4, b.max[ch], true);
      dv.setFloat32(off + 8, b.mean[ch], true);
      off += PER_CH;
    }
  }
  return buf;
}
