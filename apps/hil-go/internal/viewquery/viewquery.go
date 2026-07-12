// Package viewquery answers viewport/tier queries against a pyramid+session
// store pair. Ported from cmd/gateway/view.go and cmd/gateway/main.go's
// handleView/handleTiers so the native app can serve the same tile wire
// format the gateway does, without a running HTTP server. The gateway files
// are left untouched; this is a standalone copy for the app's transport
// (direct Go call over the Wails bridge instead of an HTTP handler).
package viewquery

import (
	"errors"

	"hil.local/daemon/internal/derive"
	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/pyramid"
	"hil.local/daemon/internal/sessionstore"
)

// MaxColumns bounds the raw-fallback reduction, matching the gateway's
// maxViewColumns.
const MaxColumns = 60_000

// View is the pre-encode result of a viewport query.
type View struct {
	Source    string
	Tier      int
	BucketSec float64
	From      float64
	Buckets   []pyramid.Bucket
}

// BuildView chooses a pyramid tier or a raw-derived reduction, mirroring
// cmd/gateway/view.go's handleView.
func BuildView(pyr *pyramid.Pyramid, store *sessionstore.Store, motor derive.Motor, from, to float64, width int) (View, error) {
	if from < 0 || to <= from || width < 1 || width > 20_000 {
		return View{}, errors.New("bad from/to/width")
	}

	secPerPx := (to - from) / float64(width)
	tier := pyr.SelectTier(secPerPx)
	if tier >= 0 {
		bucketSec := pyr.Tier(tier).BucketSec()
		indices := viewTileIndices(bucketSec, from, to)
		var out []pyramid.Bucket
		for _, index := range indices {
			buckets, _ := pyr.Tile(tier, index)
			for _, b := range buckets {
				if b.TStart >= from && b.TStart <= to {
					out = append(out, b)
				}
			}
		}
		return View{Source: "tier", Tier: tier, BucketSec: bucketSec, From: from, Buckets: out}, nil
	}

	ts, samples := store.ReadWindow(from, to)
	columns := reduceRawView(ts, samples, motor, minInt(MaxColumns, maxInt(1, width*2)))
	bucketSec := secPerPx
	if len(columns) > 1 {
		bucketSec = (to - from) / float64(len(columns))
	}
	return View{Source: "raw", Tier: 255, BucketSec: bucketSec, From: from, Buckets: columns}, nil
}

// Encode serializes a View to the wire format frontend/src/tile.ts decodes.
func Encode(v View) []byte {
	return pyramid.EncodeTile(v.Tier, v.BucketSec, v.From, v.Buckets)
}

func viewTileIndices(bucketSec, from, to float64) []int {
	tileSec := bucketSec * pyramid.BucketsPerTile
	first, last := int(from/tileSec), int(to/tileSec)
	out := make([]int, 0, last-first+1)
	for i := first; i <= last; i++ {
		out = append(out, i)
	}
	return out
}

func reduceRawView(ts []float64, samples []frame.Sample, motor derive.Motor, maxColumns int) []pyramid.Bucket {
	if len(ts) == 0 {
		return nil
	}
	columns := minInt(len(ts), maxColumns)
	out := make([]pyramid.Bucket, 0, columns)
	for c := 0; c < columns; c++ {
		i0 := c * len(ts) / columns
		i1 := (c + 1) * len(ts) / columns
		if i1 <= i0 {
			i1 = i0 + 1
		}
		values := motor.Compute(samples[i0]).Values()
		b := pyramid.Bucket{TStart: ts[i0], Min: values, Max: values, Mean: values, Count: 1}
		for i := i0 + 1; i < i1; i++ {
			v := motor.Compute(samples[i]).Values()
			b.Count++
			for ch := 0; ch < derive.NumChannels; ch++ {
				if v[ch] < b.Min[ch] {
					b.Min[ch] = v[ch]
				}
				if v[ch] > b.Max[ch] {
					b.Max[ch] = v[ch]
				}
				b.Mean[ch] += (v[ch] - b.Mean[ch]) / float64(b.Count)
			}
		}
		out = append(out, b)
	}
	return out
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}

// TierMeta describes one pyramid tier's resolution.
type TierMeta struct {
	Tier      int     `json:"tier"`
	BucketSec float64 `json:"bucketSec"`
}

// TiersMeta mirrors cmd/gateway/main.go's tiersMeta response shape.
type TiersMeta struct {
	SampleRateHz   float64    `json:"sampleRateHz"`
	BucketsPerTile int        `json:"bucketsPerTile"`
	Tiers          []TierMeta `json:"tiers"`
	TFirst         float64    `json:"tFirst"`
	TLast          float64    `json:"tLast"`
	SampleCount    int64      `json:"sampleCount"`
}

// BuildTiersMeta mirrors cmd/gateway/main.go's handleTiers.
func BuildTiersMeta(pyr *pyramid.Pyramid, store *sessionstore.Store) TiersMeta {
	meta := TiersMeta{
		SampleRateHz:   pyr.SampleRateHz(),
		BucketsPerTile: pyramid.BucketsPerTile,
	}
	for i := 0; i < pyr.NumTiers(); i++ {
		meta.Tiers = append(meta.Tiers, TierMeta{Tier: i, BucketSec: pyr.Tier(i).BucketSec()})
	}
	if store != nil {
		meta.TFirst, meta.TLast = store.Span()
		meta.SampleCount = store.Count()
	} else if bs := pyr.TierBuckets(0); len(bs) > 0 {
		meta.TFirst = bs[0].TStart
		meta.TLast = bs[len(bs)-1].TStart + pyr.Tier(0).BucketSec()
	}
	return meta
}
