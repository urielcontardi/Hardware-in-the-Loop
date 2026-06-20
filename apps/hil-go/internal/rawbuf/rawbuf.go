package rawbuf

import (
	"encoding/binary"
	"math"
	"sync"

	"hil.local/daemon/internal/frame"
)

func Encode(batch Batch) []byte {
	data := make([]byte, 12+len(batch.Samples)*frame.SampleBytes)
	binary.LittleEndian.PutUint64(data[0:8], batch.Cursor)
	binary.LittleEndian.PutUint32(data[8:12], uint32(len(batch.Samples)))
	off := 12
	for _, sample := range batch.Samples {
		binary.LittleEndian.PutUint32(data[off:], sample.TCycles)
		binary.LittleEndian.PutUint16(data[off+4:], sample.Epoch)
		values := [...]float32{sample.Ia, sample.Ib, sample.FluxA, sample.FluxB, sample.Speed}
		for i, value := range values {
			binary.LittleEndian.PutUint32(data[off+6+i*4:], math.Float32bits(value))
		}
		off += frame.SampleBytes
	}
	return data
}

// Buffer retains a bounded full-rate telemetry window with a monotonic cursor.
type Buffer struct {
	mu   sync.RWMutex
	buf  []frame.Sample
	base uint64
	next uint64
}

type Batch struct {
	Cursor  uint64         `json:"cursor"`
	Samples []frame.Sample `json:"samples"`
}

func New(capacity int) *Buffer {
	if capacity < 1 {
		capacity = 1
	}
	return &Buffer{buf: make([]frame.Sample, capacity)}
}

func (b *Buffer) Append(samples []frame.Sample) {
	b.mu.Lock()
	defer b.mu.Unlock()
	for _, sample := range samples {
		b.buf[b.next%uint64(len(b.buf))] = sample
		b.next++
		if b.next-b.base > uint64(len(b.buf)) {
			b.base = b.next - uint64(len(b.buf))
		}
	}
}

func (b *Buffer) Since(cursor uint64, limit int) Batch {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if cursor < b.base || cursor > b.next {
		cursor = b.base
	}
	end := b.next
	if limit > 0 && end-cursor > uint64(limit) {
		end = cursor + uint64(limit)
	}
	out := make([]frame.Sample, end-cursor)
	for i := range out {
		out[i] = b.buf[(cursor+uint64(i))%uint64(len(b.buf))]
	}
	return Batch{Cursor: end, Samples: out}
}

func (b *Buffer) Reset() {
	b.mu.Lock()
	b.base, b.next = 0, 0
	b.mu.Unlock()
}
