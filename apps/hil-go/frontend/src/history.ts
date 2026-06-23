export interface HistoricalSample {
  Ia: number;
  Ib: number;
  FluxA: number;
  FluxB: number;
  Speed: number;
}

export interface HistoricalRawWindow {
  t: number[];
  samples: HistoricalSample[];
}

// Wire format produced by gateway handleWindow:
// count u32, then t f64 + five f32 values per sample.
export function decodeHistoricalWindow(buf: ArrayBuffer): HistoricalRawWindow {
  if (buf.byteLength < 4) throw new Error("truncated historical window");
  const dv = new DataView(buf);
  const count = dv.getUint32(0, true);
  const recordBytes = 28;
  if (buf.byteLength !== 4 + count * recordBytes) throw new Error("invalid historical window size");
  const t = new Array<number>(count);
  const samples = new Array<HistoricalSample>(count);
  let off = 4;
  for (let i = 0; i < count; i++, off += recordBytes) {
    t[i] = dv.getFloat64(off, true);
    samples[i] = {
      Ia: dv.getFloat32(off + 8, true),
      Ib: dv.getFloat32(off + 12, true),
      FluxA: dv.getFloat32(off + 16, true),
      FluxB: dv.getFloat32(off + 20, true),
      Speed: dv.getFloat32(off + 24, true),
    };
  }
  return { t, samples };
}
