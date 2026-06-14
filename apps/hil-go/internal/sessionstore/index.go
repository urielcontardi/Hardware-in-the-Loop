package sessionstore

import "sort"

// index is a sparse, in-RAM time->byte-offset map (one entry per block of
// samples). Offsets are byte positions of the first sample record in a block.
type index struct {
	t   []float64
	off []int64
}

func (ix *index) add(t float64, off int64) {
	ix.t = append(ix.t, t)
	ix.off = append(ix.off, off)
}

// floorOffset returns the offset of the largest indexed time <= target.
func (ix *index) floorOffset(target float64) (int64, bool) {
	if len(ix.t) == 0 || target < ix.t[0] {
		return 0, false
	}
	i := sort.Search(len(ix.t), func(i int) bool { return ix.t[i] > target })
	if i == 0 {
		return 0, false
	}
	return ix.off[i-1], true
}

func (ix *index) reset() { ix.t, ix.off = nil, nil }
