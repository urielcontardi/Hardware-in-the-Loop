import { describe, it, expect } from "vitest";
import { decodeSeries, NUM_CH } from "./series";

function buildBuf(cols: { t: number; mm: number[][] }[]): ArrayBuffer {
  const recSize = 4 + NUM_CH * 8;
  const buf = new ArrayBuffer(5 + cols.length * recSize);
  const dv = new DataView(buf);
  dv.setUint32(0, cols.length, true);
  dv.setUint8(4, NUM_CH);
  let off = 5;
  for (const c of cols) {
    dv.setFloat32(off, c.t, true); off += 4;
    for (let ch = 0; ch < NUM_CH; ch++) {
      dv.setFloat32(off, c.mm[ch][0], true);
      dv.setFloat32(off + 4, c.mm[ch][1], true);
      off += 8;
    }
  }
  return buf;
}

describe("decodeSeries", () => {
  it("round-trips a column", () => {
    const mm = Array.from({ length: NUM_CH }, (_, i) => [i, i + 1]);
    const out = decodeSeries(buildBuf([{ t: 2.5, mm }]));
    expect(out.t.length).toBe(1);
    expect(out.t[0]).toBeCloseTo(2.5, 5);
    expect(out.min[0][0]).toBeCloseTo(0, 5);
    expect(out.max[0][0]).toBeCloseTo(1, 5);
  });
});
