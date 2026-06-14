// Package series turns a full-rate window of alpha-beta samples into a faithful
// min/max envelope sized to the display width, applying derived channels at
// full rate first.
package series

import (
	"encoding/binary"
	"math"

	"hil.local/daemon/internal/derive"
	"hil.local/daemon/internal/frame"
)

// Column is one display column: a min/max pair per channel and its time.
type Column struct {
	T   float64
	Min [derive.NumChannels]float64
	Max [derive.NumChannels]float64
}

// ReduceWindow computes derived channels per sample, then emits one Column per
// display pixel via min/max bucketing. If there are <= 2*width samples, every
// sample is returned raw (min==max) so zoom-in shows the true trace.
func ReduceWindow(m derive.Motor, ts []float64, ss []frame.Sample, width int) []Column {
	if width < 1 {
		width = 1
	}
	n := len(ss)
	if n == 0 {
		return nil
	}
	if n <= 2*width {
		out := make([]Column, n)
		for i := range ss {
			v := m.Compute(ss[i]).Values()
			out[i] = Column{T: ts[i], Min: v, Max: v}
		}
		return out
	}
	out := make([]Column, 0, width)
	per := float64(n) / float64(width)
	for col := 0; col < width; col++ {
		lo := int(float64(col) * per)
		hi := int(float64(col+1) * per)
		if hi > n {
			hi = n
		}
		if lo >= hi {
			continue
		}
		c := Column{T: ts[lo]}
		first := m.Compute(ss[lo]).Values()
		c.Min, c.Max = first, first
		for i := lo + 1; i < hi; i++ {
			v := m.Compute(ss[i]).Values()
			for ch := 0; ch < derive.NumChannels; ch++ {
				if v[ch] < c.Min[ch] {
					c.Min[ch] = v[ch]
				}
				if v[ch] > c.Max[ch] {
					c.Max[ch] = v[ch]
				}
			}
		}
		out = append(out, c)
	}
	return out
}

// Encode serializes columns to the compact binary the front end parses.
// Wire format (LE): count uint32, nch uint8, then per column: t float32,
// followed by nch×(min float32, max float32).
func Encode(cols []Column) []byte {
	const colHdr = 4
	perCh := 8
	recSize := colHdr + derive.NumChannels*perCh
	b := make([]byte, 5+len(cols)*recSize)
	binary.LittleEndian.PutUint32(b[0:4], uint32(len(cols)))
	b[4] = derive.NumChannels
	off := 5
	for _, c := range cols {
		binary.LittleEndian.PutUint32(b[off:], math.Float32bits(float32(c.T)))
		off += 4
		for ch := 0; ch < derive.NumChannels; ch++ {
			binary.LittleEndian.PutUint32(b[off:], math.Float32bits(float32(c.Min[ch])))
			binary.LittleEndian.PutUint32(b[off+4:], math.Float32bits(float32(c.Max[ch])))
			off += 8
		}
	}
	return b
}
