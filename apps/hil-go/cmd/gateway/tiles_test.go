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
