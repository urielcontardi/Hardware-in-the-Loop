package main

import (
	"net/http/httptest"
	"path/filepath"
	"testing"

	"hil.local/daemon/internal/derive"
	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/overview"
	"hil.local/daemon/internal/sessionstore"
)

func TestHandleSeriesReturnsColumns(t *testing.T) {
	dir := t.TempDir()
	st, _ := sessionstore.Open(filepath.Join(dir, "s.bin"), 16)
	defer st.Close()
	for i := 0; i < 1000; i++ {
		st.Append(float64(i)*1e-5, frame.Sample{Ia: float32(i % 7)})
	}
	s := &server{store: st, overview: overview.New(0.05), motor: derive.DefaultMotor}
	req := httptest.NewRequest("GET", "/api/series?from=0&to=0.01&width=100", nil)
	rec := httptest.NewRecorder()
	s.handleSeries(rec, req)
	if rec.Code != 200 {
		t.Fatalf("status %d", rec.Code)
	}
	if rec.Body.Len() < 5 {
		t.Fatalf("empty body")
	}
}
