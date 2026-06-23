package main

import (
	"encoding/binary"
	"math"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/sessionstore"
)

func TestHandleWindowReturnsFullRateSamples(t *testing.T) {
	st, err := sessionstore.Open(filepath.Join(t.TempDir(), "live.bin"), 2)
	if err != nil {
		t.Fatal(err)
	}
	defer st.Close()
	for i := 0; i < 10; i++ {
		st.Append(float64(i)*0.001, frame.Sample{Ia: float32(i), Ib: float32(-i)})
	}
	s := &server{store: st}
	req := httptest.NewRequest(http.MethodGet, "/api/window?from=0.003&to=0.005", nil)
	rec := httptest.NewRecorder()
	s.handleWindow(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	b := rec.Body.Bytes()
	if got := binary.LittleEndian.Uint32(b[:4]); got != 3 {
		t.Fatalf("count=%d want 3", got)
	}
	if got := math.Float64frombits(binary.LittleEndian.Uint64(b[4:12])); math.Abs(got-0.003) > 1e-12 {
		t.Fatalf("first time=%g want 0.003", got)
	}
	if got := math.Float32frombits(binary.LittleEndian.Uint32(b[12:16])); got != 3 {
		t.Fatalf("first Ia=%g want 3", got)
	}
	if cc := rec.Header().Get("Cache-Control"); cc != "no-store" {
		t.Fatalf("cache=%q", cc)
	}
}

func TestHandleWindowRejectsInvalidRange(t *testing.T) {
	s := &server{}
	req := httptest.NewRequest(http.MethodGet, "/api/window?from=2&to=1", nil)
	rec := httptest.NewRecorder()
	s.handleWindow(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status=%d want 400", rec.Code)
	}
}
