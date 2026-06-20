package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"hil.local/daemon/internal/derive"
	"hil.local/daemon/internal/pyramid"
)

func newTestServer() *server {
	return &server{
		pyramid: pyramid.New(10000),
		motor:   derive.DefaultMotor,
	}
}

func TestHandleTiersJSON(t *testing.T) {
	s := newTestServer()
	var v [derive.NumChannels]float64
	v[0] = 1
	s.pyramid.Push(0.0, v)
	s.pyramid.Push(0.5, v)

	req := httptest.NewRequest(http.MethodGet, "/api/tiers", nil)
	rec := httptest.NewRecorder()
	s.handleTiers(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var meta tiersMeta
	if err := json.Unmarshal(rec.Body.Bytes(), &meta); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if meta.SampleRateHz != 10000 {
		t.Errorf("sampleRate = %v, want 10000", meta.SampleRateHz)
	}
	if len(meta.Tiers) != 4 {
		t.Fatalf("tiers = %d, want 4", len(meta.Tiers))
	}
	if meta.Tiers[0].BucketSec != 0.001 {
		t.Errorf("tier0 bucketSec = %v, want 0.001", meta.Tiers[0].BucketSec)
	}
	if meta.TLast < 0.5 {
		t.Errorf("tLast = %v, want >= 0.5", meta.TLast)
	}
}

func TestHandleTilesBytesAndCache(t *testing.T) {
	s := newTestServer()
	var v [derive.NumChannels]float64
	// Fill past tile 0 of T1 so it is sealed.
	for i := 0; i < 1600; i++ {
		v[0] = float64(i)
		s.pyramid.Push(float64(i)*0.001, v)
	}
	req := httptest.NewRequest(http.MethodGet, "/api/tiles?tier=0&index=0", nil)
	rec := httptest.NewRecorder()
	s.handleTiles(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	body := rec.Body.Bytes()
	if body[0] != 0 {
		t.Errorf("tier byte = %d, want 0", body[0])
	}
	if cc := rec.Header().Get("Cache-Control"); cc == "" || cc == "no-store" {
		t.Errorf("sealed tile Cache-Control = %q, want immutable", cc)
	}

	// Trailing tile must be no-store.
	req2 := httptest.NewRequest(http.MethodGet, "/api/tiles?tier=0&index=1", nil)
	rec2 := httptest.NewRecorder()
	s.handleTiles(rec2, req2)
	if cc := rec2.Header().Get("Cache-Control"); cc != "no-store" {
		t.Errorf("trailing tile Cache-Control = %q, want no-store", cc)
	}
}

func TestHandleTilesBadTier(t *testing.T) {
	s := newTestServer()
	req := httptest.NewRequest(http.MethodGet, "/api/tiles?tier=9&index=0", nil)
	rec := httptest.NewRecorder()
	s.handleTiles(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}
