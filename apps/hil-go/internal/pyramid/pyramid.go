// Package pyramid keeps a multi-resolution min/max/mean envelope of every
// display channel across several fixed bucket widths (tiers). It backs the
// tile API so any zoom level renders in O(pixels) instead of O(samples). The
// raw tier (T0) lives in rawbuf/store, not here; pyramid covers T1..T4.
package pyramid

import (
	"sync"

	"hil.local/daemon/internal/derive"
)

// BucketsPerTile is the fixed number of buckets per cacheable tile.
const BucketsPerTile = 1024

// defaultBucketSecs are the tier widths in seconds (ascending).
var defaultBucketSecs = []float64{0.001, 0.020, 0.500, 10.0}

// Bucket is the min/max/mean envelope of one time bucket for all channels.
type Bucket struct {
	TStart float64
	Min    [derive.NumChannels]float64
	Max    [derive.NumChannels]float64
	Mean   [derive.NumChannels]float64
	Count  int
}

type tier struct {
	bucketSec float64
	cols      []Bucket
	curIndex  int64
	have      bool
}

// Buckets returns the tier's buckets in time order (read-only use).
func (t *tier) Buckets() []Bucket { return t.cols }

// BucketSec reports the tier resolution in seconds.
func (t *tier) BucketSec() float64 { return t.bucketSec }

func (t *tier) push(ts float64, v [derive.NumChannels]float64) {
	idx := int64(ts / t.bucketSec)
	if !t.have || idx != t.curIndex {
		t.cols = append(t.cols, Bucket{
			TStart: float64(idx) * t.bucketSec,
			Min:    v, Max: v, Mean: v, Count: 1,
		})
		t.curIndex = idx
		t.have = true
		return
	}
	b := &t.cols[len(t.cols)-1]
	b.Count++
	n := float64(b.Count)
	for i := 0; i < derive.NumChannels; i++ {
		if v[i] < b.Min[i] {
			b.Min[i] = v[i]
		}
		if v[i] > b.Max[i] {
			b.Max[i] = v[i]
		}
		b.Mean[i] += (v[i] - b.Mean[i]) / n // running mean
	}
}

// Pyramid is the concurrency-safe set of tiers.
type Pyramid struct {
	mu    sync.RWMutex
	tiers []*tier
	rateH float64
}

// New builds a pyramid for the given telemetry sample rate (Hz).
func New(sampleRateHz float64) *Pyramid {
	if sampleRateHz <= 0 {
		sampleRateHz = 10000
	}
	ts := make([]*tier, len(defaultBucketSecs))
	for i, bs := range defaultBucketSecs {
		ts[i] = &tier{bucketSec: bs, curIndex: -1}
	}
	return &Pyramid{tiers: ts, rateH: sampleRateHz}
}

// Push folds one derived-channel sample into every tier independently. Folding
// from raw into each tier (rather than cascading) keeps min/max/mean exact.
func (p *Pyramid) Push(t float64, v [derive.NumChannels]float64) {
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, tr := range p.tiers {
		tr.push(t, v)
	}
}

// NumTiers reports how many tiers exist (T1..Tn).
func (p *Pyramid) NumTiers() int { return len(p.tiers) }

// Tier returns tier i (0 == finest, T1).
func (p *Pyramid) Tier(i int) *tier { return p.tiers[i] }

// SampleRateHz reports the configured rate.
func (p *Pyramid) SampleRateHz() float64 { return p.rateH }

// Reset clears every tier (call on new run/epoch/motor change).
func (p *Pyramid) Reset() {
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, tr := range p.tiers {
		tr.cols, tr.curIndex, tr.have = nil, -1, false
	}
}
