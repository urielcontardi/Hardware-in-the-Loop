package main

// sampleClock converts run-local 32-bit cycle counters (100 MHz) into seconds,
// handling 2^32 wrap and per-epoch resets (the counter restarts at 0 each run).
type sampleClock struct {
	haveEpoch bool
	epoch     uint16
	last      uint32
	wrap      uint64
}

const sampleClockHz = 100_000_000

func (c *sampleClock) seconds(cycles uint32, epoch uint16) float64 {
	if !c.haveEpoch || epoch != c.epoch {
		c.haveEpoch, c.epoch, c.last, c.wrap = true, epoch, cycles, 0
		return float64(cycles) / sampleClockHz
	}
	if cycles < c.last && c.last-cycles > 0x80000000 {
		c.wrap += 1 << 32
	}
	c.last = cycles
	return float64(c.wrap+uint64(cycles)) / sampleClockHz
}
