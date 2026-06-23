package main

import (
	"encoding/binary"
	"math"
	"net/http"
	"strconv"
)

// A fine historical viewport is bounded so one request cannot read an entire
// long run into memory. At 100 ksample/s this allows up to 2.5 seconds of raw
// data, far wider than the windows for which the 1 ms pyramid is insufficient.
const historicalWindowMaxSamples = 250_000

func (s *server) handleWindow(w http.ResponseWriter, r *http.Request) {
	from, errFrom := strconv.ParseFloat(r.URL.Query().Get("from"), 64)
	to, errTo := strconv.ParseFloat(r.URL.Query().Get("to"), 64)
	if errFrom != nil || errTo != nil || from < 0 || to < from {
		http.Error(w, "bad from/to", http.StatusBadRequest)
		return
	}

	s.ingestMu.Lock()
	ts, samples := s.store.ReadWindow(from, to)
	s.ingestMu.Unlock()
	if len(ts) > historicalWindowMaxSamples {
		http.Error(w, "raw window too large; use pyramid tiles", http.StatusRequestEntityTooLarge)
		return
	}

	// count u32, then count records of:
	// t f64 + Ia/Ib/FluxA/FluxB/Speed f32 = 28 bytes.
	body := make([]byte, 4+len(ts)*28)
	binary.LittleEndian.PutUint32(body[0:4], uint32(len(ts)))
	off := 4
	for i, t := range ts {
		binary.LittleEndian.PutUint64(body[off:off+8], math.Float64bits(t))
		binary.LittleEndian.PutUint32(body[off+8:off+12], math.Float32bits(samples[i].Ia))
		binary.LittleEndian.PutUint32(body[off+12:off+16], math.Float32bits(samples[i].Ib))
		binary.LittleEndian.PutUint32(body[off+16:off+20], math.Float32bits(samples[i].FluxA))
		binary.LittleEndian.PutUint32(body[off+20:off+24], math.Float32bits(samples[i].FluxB))
		binary.LittleEndian.PutUint32(body[off+24:off+28], math.Float32bits(samples[i].Speed))
		off += 28
	}
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Cache-Control", "no-store")
	_, _ = w.Write(body)
}
