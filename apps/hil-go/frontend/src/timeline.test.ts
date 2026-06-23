import { describe, expect, it } from "vitest";
import { secondsFromTelemetryOrigin } from "./timeline";

describe("secondsFromTelemetryOrigin", () => {
  it("places telemetry and PWM counters on the same origin", () => {
    const base = 200_000_000;
    expect(secondsFromTelemetryOrigin(205_000_000, 0, base, 100_000_000)).toBeCloseTo(0.05);
    expect(secondsFromTelemetryOrigin(205_000_000, 0, base, 100_000_000)).toBeCloseTo(0.05);
  });

  it("preserves the origin through a 32-bit wrap", () => {
    const base = 0xfffffff0;
    expect(secondsFromTelemetryOrigin(0x10, 2 ** 32, base, 100_000_000)).toBeCloseTo(0x20 / 100_000_000);
  });
});
