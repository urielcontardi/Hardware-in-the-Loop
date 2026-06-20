package pyramid

import (
	"encoding/binary"
	"math"

	"hil.local/daemon/internal/derive"
)

// EncodeTile serializes a tile to the compact binary the front end parses.
// Wire format (LE):
//
//	header: tier u8, bucketsCount u16, nch u8, bucketSec f32, tStart0 f32
//	per bucket: tStart f32, then nch×(min f32, max f32, mean f32)
func EncodeTile(tier int, bucketSec, tStart0 float64, buckets []Bucket) []byte {
	const headerBytes = 13 // 1+2+1+4+4
	const perCh = 12       // min,max,mean
	recSize := 4 + derive.NumChannels*perCh
	b := make([]byte, headerBytes+len(buckets)*recSize)
	b[0] = byte(tier)
	binary.LittleEndian.PutUint16(b[1:3], uint16(len(buckets)))
	b[3] = derive.NumChannels
	binary.LittleEndian.PutUint32(b[4:8], math.Float32bits(float32(bucketSec)))
	binary.LittleEndian.PutUint32(b[8:12], math.Float32bits(float32(tStart0)))
	// b[12] reserved/padding so the header is 13 bytes and bucket records align
	// to a clean offset; kept zero.
	off := headerBytes
	for _, bk := range buckets {
		binary.LittleEndian.PutUint32(b[off:], math.Float32bits(float32(bk.TStart)))
		off += 4
		for ch := 0; ch < derive.NumChannels; ch++ {
			binary.LittleEndian.PutUint32(b[off:], math.Float32bits(float32(bk.Min[ch])))
			binary.LittleEndian.PutUint32(b[off+4:], math.Float32bits(float32(bk.Max[ch])))
			binary.LittleEndian.PutUint32(b[off+8:], math.Float32bits(float32(bk.Mean[ch])))
			off += perCh
		}
	}
	return b
}
