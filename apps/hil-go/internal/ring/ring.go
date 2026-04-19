// Package ring provides a lock-free SPSC ring buffer for telemetry samples.
// Single producer (UDP receiver goroutine) + single consumer (broadcast goroutine).
package ring

import (
	"sync/atomic"

	"hil.local/daemon/internal/frame"
)

// Ring is a power-of-two, lock-free single-producer/single-consumer ring buffer.
type Ring struct {
	buf  []frame.Sample
	mask uint64
	head atomic.Uint64 // written by producer
	tail atomic.Uint64 // read by consumer
}

// New creates a Ring with capacity rounded up to the next power of two.
func New(capacity uint64) *Ring {
	size := uint64(1)
	for size < capacity {
		size <<= 1
	}
	return &Ring{buf: make([]frame.Sample, size), mask: size - 1}
}

// Push adds a sample. Returns false and drops silently if full.
func (r *Ring) Push(s frame.Sample) bool {
	head := r.head.Load()
	if head-r.tail.Load() >= uint64(len(r.buf)) {
		return false // full
	}
	r.buf[head&r.mask] = s
	r.head.Add(1)
	return true
}

// PopN drains up to max samples into dst and returns the count.
func (r *Ring) PopN(dst []frame.Sample) int {
	tail := r.tail.Load()
	head := r.head.Load()
	avail := int(head - tail)
	if avail <= 0 {
		return 0
	}
	n := avail
	if n > len(dst) {
		n = len(dst)
	}
	for i := range n {
		dst[i] = r.buf[(tail+uint64(i))&r.mask]
	}
	r.tail.Add(uint64(n))
	return n
}

// Len returns the number of samples currently in the buffer.
func (r *Ring) Len() int {
	return int(r.head.Load() - r.tail.Load())
}
