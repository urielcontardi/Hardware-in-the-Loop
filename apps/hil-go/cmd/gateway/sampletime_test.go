package main

import "testing"

func TestSampleClockWrap(t *testing.T) {
	var c sampleClock
	const hz = 100_000_000
	if got := c.seconds(0, 1); got != 0 {
		t.Errorf("first seconds=%v want 0", got)
	}
	_ = c.seconds(0xFFFFFFF0, 1)
	got := c.seconds(0x00000010, 1) // wrapped by 2^32
	want := float64(0x100000010) / hz
	if got < want-1e-9 || got > want+1e-9 {
		t.Errorf("wrapped seconds=%v want %v", got, want)
	}
}

func TestSampleClockEpochResets(t *testing.T) {
	var c sampleClock
	_ = c.seconds(5000, 1)
	if got := c.seconds(0, 2); got != 0 {
		t.Errorf("epoch change should reset to 0, got %v", got)
	}
}
