import { describe, expect, it } from "vitest";
import { recordStep, stepValueAt, type StepPoint } from "./stepseries";

describe("step series", () => {
  it("holds each command until the next event", () => {
    const points: StepPoint[] = [];
    recordStep(points, 0, 0);
    recordStep(points, 6, 5);
    recordStep(points, 8, 15);
    recordStep(points, 12, 0);
    expect(stepValueAt(points, 5.99)).toBe(0);
    expect(stepValueAt(points, 6)).toBe(5);
    expect(stepValueAt(points, 9)).toBe(15);
    expect(stepValueAt(points, 13)).toBe(0);
  });

  it("replaces a command at the same timestamp", () => {
    const points: StepPoint[] = [];
    recordStep(points, 0, 5);
    recordStep(points, 0, 10);
    expect(points).toEqual([{ t: 0, value: 10 }]);
  });
});
