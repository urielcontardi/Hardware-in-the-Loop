package main

// sampleClock converts 32-bit FPGA counters (100 MHz) into seconds. The DMA
// timestamp currently carries the hardware counter value at acquisition time;
// it is not guaranteed to be zero at Run, so each epoch is normalized to the
// first counter observed in that epoch.
type sampleClock struct {
	haveEpoch bool
	epoch     uint16
	last      uint32
	wrap      uint64
	baseAbs   uint64
	lastSec   float64
}

const sampleClockHz = 100_000_000

func (c *sampleClock) seconds(cycles uint32, epoch uint16) (float64, bool) {
	if !c.haveEpoch || epoch != c.epoch {
		c.haveEpoch, c.epoch, c.last, c.wrap = true, epoch, cycles, 0
		c.baseAbs = uint64(cycles)
		c.lastSec = 0
		return 0, true
	}
	if cycles < c.last && c.last-cycles > 0x80000000 {
		c.wrap += 1 << 32
	} else if cycles <= c.last {
		return 0, false
	}
	c.last = cycles
	absCycles := c.wrap + uint64(cycles)
	if absCycles < c.baseAbs {
		return 0, false
	}
	sec := float64(absCycles-c.baseAbs) / sampleClockHz
	if sec <= c.lastSec {
		return 0, false
	}
	c.lastSec = sec
	return sec, true
}
