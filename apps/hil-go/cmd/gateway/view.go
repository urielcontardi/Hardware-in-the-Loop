package main

import (
	"net/http"
	"strconv"

	"hil.local/daemon/internal/derive"
	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/pyramid"
)

const maxViewColumns = 60_000

// handleView is the only viewport query contract. It chooses raw-derived
// columns or a pyramid tier internally and always returns the tile wire format.
func (s *server) handleView(w http.ResponseWriter, r *http.Request) {
	from, errFrom := strconv.ParseFloat(r.URL.Query().Get("from"), 64)
	to, errTo := strconv.ParseFloat(r.URL.Query().Get("to"), 64)
	width, errWidth := strconv.Atoi(r.URL.Query().Get("width"))
	if errFrom != nil || errTo != nil || errWidth != nil || from < 0 || to <= from || width < 1 || width > 20_000 {
		http.Error(w, "bad from/to/width", http.StatusBadRequest)
		return
	}

	secPerPx := (to - from) / float64(width)
	s.ingestMu.Lock()
	tier := s.pyramid.SelectTier(secPerPx)
	if tier >= 0 {
		bucketSec := s.pyramid.Tier(tier).BucketSec()
		indices := viewTileIndices(bucketSec, from, to)
		var out []pyramid.Bucket
		for _, index := range indices {
			buckets, _ := s.pyramid.Tile(tier, index)
			for _, b := range buckets {
				if b.TStart >= from && b.TStart <= to {
					out = append(out, b)
				}
			}
		}
		s.ingestMu.Unlock()
		writeView(w, "tier", tier, bucketSec, from, out)
		return
	}

	ts, samples := s.store.ReadWindow(from, to)
	motor := s.motor
	s.ingestMu.Unlock()
	columns := reduceRawView(ts, samples, motor, minInt(maxViewColumns, maxInt(1, width*2)))
	bucketSec := secPerPx
	if len(columns) > 1 {
		bucketSec = (to - from) / float64(len(columns))
	}
	writeView(w, "raw", 255, bucketSec, from, columns)
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

func writeView(w http.ResponseWriter, source string, tier int, bucketSec, from float64, buckets []pyramid.Bucket) {
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-HIL-Source", source)
	w.Header().Set("X-HIL-Tier", strconv.Itoa(tier))
	w.Header().Set("X-HIL-Columns", strconv.Itoa(len(buckets)))
	_, _ = w.Write(pyramid.EncodeTile(tier, bucketSec, from, buckets))
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
