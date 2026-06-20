package main

import "testing"

func TestSampleClockNormalizesEpochToZero(t *testing.T) {
	var c sampleClock
	if got, ok := c.seconds(2_878_963_557, 11); !ok || got != 0 {
		t.Fatalf("first seconds=%v ok=%v, want 0/true", got, ok)
	}
	got, ok := c.seconds(2_878_964_557, 11)
	if !ok {
		t.Fatal("second sample rejected")
	}
	if got < 9.999e-6 || got > 10.001e-6 {
		t.Fatalf("normalized seconds=%v want 10us", got)
	}
}

func TestSampleClockWrap(t *testing.T) {
	var c sampleClock
	const hz = 100_000_000
	if got, ok := c.seconds(0xFFFFFFF0, 1); !ok || got != 0 {
		t.Errorf("first seconds=%v ok=%v want 0/true", got, ok)
	}
	got, ok := c.seconds(0x00000010, 1) // wrapped by 2^32
	if !ok {
		t.Fatal("wrapped sample was rejected")
	}
	want := float64(0x20) / hz
	if got < want-1e-9 || got > want+1e-9 {
		t.Errorf("wrapped seconds=%v want %v", got, want)
	}
}

func TestSampleClockEpochResets(t *testing.T) {
	var c sampleClock
	_, _ = c.seconds(5000, 1)
	if got, ok := c.seconds(123456, 2); !ok || got != 0 {
		t.Errorf("epoch change should reset to 0, got %v ok=%v", got, ok)
	}
}

func TestSampleClockRejectsFrozenCounterWithinEpoch(t *testing.T) {
	var c sampleClock
	if _, ok := c.seconds(1000, 1); !ok {
		t.Fatal("first sample rejected")
	}
	if _, ok := c.seconds(1000, 1); ok {
		t.Fatal("duplicate timestamp accepted")
	}
}
