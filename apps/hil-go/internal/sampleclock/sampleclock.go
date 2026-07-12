// Package sampleclock converts 32-bit FPGA counters (100 MHz) into seconds.
// Ported from cmd/gateway/sampletime.go's sampleClock so the native app can
// feed the same pyramid/sessionstore pipeline the gateway uses; the gateway
// file is left untouched.
package sampleclock

// Clock normalizes each epoch to the first counter observed in that epoch.
// The DMA timestamp is not guaranteed to be zero at Run.
type Clock struct {
	HaveEpoch bool
	Epoch     uint16
	last      uint32
	wrap      uint64
	baseAbs   uint64
	lastSec   float64
}

const Hz = 100_000_000

// Seconds converts one sample's (cycles, epoch) into run-local seconds. ok is
// false for a stale/duplicate/out-of-order sample that the caller should drop.
func (c *Clock) Seconds(cycles uint32, epoch uint16) (sec float64, ok bool) {
	if !c.HaveEpoch || epoch != c.Epoch {
		c.HaveEpoch, c.Epoch, c.last, c.wrap = true, epoch, cycles, 0
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
	sec = float64(absCycles-c.baseAbs) / Hz
	if sec <= c.lastSec {
		return 0, false
	}
	c.lastSec = sec
	return sec, true
}
