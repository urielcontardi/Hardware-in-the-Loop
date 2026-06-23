package main

import (
	"encoding/binary"
	"math"
	"net/http/httptest"
	"testing"

	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/rawbuf"
)

func TestHandleRawWritesCompactIncrementalBatch(t *testing.T) {
	raw := rawbuf.New(8)
	raw.Append([]frame.Sample{{
		TCycles: 123, Epoch: 7, Ia: 1, Ib: 2, FluxA: 3, FluxB: 4, Speed: 5,
	}})
	s := &server{raw: raw}
	req := httptest.NewRequest("GET", "/api/raw?cursor=0&limit=20", nil)
	res := httptest.NewRecorder()

	s.handleRaw(res, req)

	data := res.Body.Bytes()
	if len(data) != 12+frame.SampleBytes {
		t.Fatalf("payload bytes=%d", len(data))
	}
	if cursor := binary.LittleEndian.Uint64(data[:8]); cursor != 1 {
		t.Fatalf("cursor=%d", cursor)
	}
	if count := binary.LittleEndian.Uint32(data[8:12]); count != 1 {
		t.Fatalf("count=%d", count)
	}
	if cycles := binary.LittleEndian.Uint32(data[12:16]); cycles != 123 {
		t.Fatalf("cycles=%d", cycles)
	}
	if epoch := binary.LittleEndian.Uint16(data[16:18]); epoch != 7 {
		t.Fatalf("epoch=%d", epoch)
	}
	if ia := math.Float32frombits(binary.LittleEndian.Uint32(data[18:22])); ia != 1 {
		t.Fatalf("Ia=%g", ia)
	}
}

func TestHandleRawLatestStartsAtLiveTail(t *testing.T) {
	raw := rawbuf.New(8)
	raw.Append([]frame.Sample{{TCycles: 1}, {TCycles: 2}, {TCycles: 3}})
	s := &server{raw: raw}

	first := httptest.NewRecorder()
	s.handleRaw(first, httptest.NewRequest("GET", "/api/raw?cursor=latest&limit=20", nil))
	if cursor := binary.LittleEndian.Uint64(first.Body.Bytes()[:8]); cursor != 3 {
		t.Fatalf("tail cursor=%d want 3", cursor)
	}
	if count := binary.LittleEndian.Uint32(first.Body.Bytes()[8:12]); count != 0 {
		t.Fatalf("tail replayed %d old samples", count)
	}

	raw.Append([]frame.Sample{{TCycles: 4}})
	next := httptest.NewRecorder()
	s.handleRaw(next, httptest.NewRequest("GET", "/api/raw?cursor=3&limit=20", nil))
	if count := binary.LittleEndian.Uint32(next.Body.Bytes()[8:12]); count != 1 {
		t.Fatalf("live count=%d want 1", count)
	}
}
