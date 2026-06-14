// Package overview keeps a bounded, whole-session min/max envelope of every
// display channel in fixed time buckets. It backs zoomed-out viewport queries
// so a sinusoid renders as a correct-amplitude band instead of a triangle.
package overview

import (
	"sync"

	"hil.local/daemon/internal/derive"
)

// Column is the min/max envelope of one time bucket.
type Column struct {
	TStart float64
	Min    [derive.NumChannels]float64
	Max    [derive.NumChannels]float64
}

// Overview accumulates Columns at a fixed bucket width (seconds).
type Overview struct {
	mu       sync.RWMutex
	bucketS  float64
	cols     []Column
	curIndex int64
	have     bool
}

// New creates an Overview with the given bucket width in seconds.
func New(bucketSeconds float64) *Overview {
	if bucketSeconds <= 0 {
		bucketSeconds = 0.050
	}
	return &Overview{bucketS: bucketSeconds, curIndex: -1}
}

// Push folds one sample (time in seconds, channel values) into its bucket.
func (o *Overview) Push(t float64, v [derive.NumChannels]float64) {
	o.mu.Lock()
	defer o.mu.Unlock()
	idx := int64(t / o.bucketS)
	if !o.have || idx != o.curIndex {
		o.cols = append(o.cols, Column{TStart: float64(idx) * o.bucketS, Min: v, Max: v})
		o.curIndex = idx
		o.have = true
		return
	}
	c := &o.cols[len(o.cols)-1]
	for i := 0; i < derive.NumChannels; i++ {
		if v[i] < c.Min[i] {
			c.Min[i] = v[i]
		}
		if v[i] > c.Max[i] {
			c.Max[i] = v[i]
		}
	}
}

// Query returns the columns whose TStart is within [from, to).
func (o *Overview) Query(from, to float64) []Column {
	o.mu.RLock()
	defer o.mu.RUnlock()
	out := make([]Column, 0)
	for _, c := range o.cols {
		if c.TStart >= from && c.TStart < to {
			out = append(out, c)
		}
	}
	return out
}

// BucketSeconds reports the tier resolution.
func (o *Overview) BucketSeconds() float64 { return o.bucketS }

// Reset clears all buckets (call on a new run/epoch).
func (o *Overview) Reset() {
	o.mu.Lock()
	o.cols, o.curIndex, o.have = nil, -1, false
	o.mu.Unlock()
}
