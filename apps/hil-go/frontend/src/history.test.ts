import { describe, expect, it } from "vitest";
import { decodeHistoricalWindow } from "./history";

describe("decodeHistoricalWindow", () => {
  it("decodes full-rate timestamp and solver states", () => {
    const buf = new ArrayBuffer(4 + 28);
    const dv = new DataView(buf);
    dv.setUint32(0, 1, true);
    dv.setFloat64(4, 2.125, true);
    [1, -2, 3, -4, 5].forEach((v, i) => dv.setFloat32(12 + i * 4, v, true));
    const got = decodeHistoricalWindow(buf);
    expect(got.t).toEqual([2.125]);
    expect(got.samples[0]).toEqual({ Ia: 1, Ib: -2, FluxA: 3, FluxB: -4, Speed: 5 });
  });

  it("rejects a malformed payload", () => {
    const buf = new ArrayBuffer(4);
    new DataView(buf).setUint32(0, 1, true);
    expect(() => decodeHistoricalWindow(buf)).toThrow("invalid historical window size");
  });
});
