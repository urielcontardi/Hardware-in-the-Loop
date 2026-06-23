// Convert any FPGA stream to the session timeline established by the first
// telemetry sample. Telemetry and PWM must call this with the same base.
export function secondsFromTelemetryOrigin(
  rawCycles: number, wrapCycles: number, telemetryBaseCycles: number, clockHz: number,
): number {
  return (wrapCycles + rawCycles - telemetryBaseCycles) / clockHz;
}
