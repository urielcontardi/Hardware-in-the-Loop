package main

import (
	"encoding/binary"
	"math"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strconv"
	"testing"

	"hil.local/daemon/internal/derive"
	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/pyramid"
	"hil.local/daemon/internal/sessionstore"
)

func newViewTestServer(t *testing.T, count int) *server {
	t.Helper()
	st, err := sessionstore.Open(filepath.Join(t.TempDir(), "view.bin"), 32)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = st.Close() })
	s := &server{store: st, pyramid: pyramid.New(10000), motor: derive.DefaultMotor}
	for i := 0; i < count; i++ {
		ts := float64(i) / 10000
		sm := frame.Sample{Ia: float32(math.Sin(2 * math.Pi * 50 * ts)), Ib: float32(math.Cos(2 * math.Pi * 50 * ts))}
		st.Append(ts, sm)
		s.pyramid.Push(ts, s.motor.Compute(sm).Values())
	}
	return s
}

func viewCount(t *testing.T, body []byte) int {
	t.Helper()
	if len(body) < 13 {
		t.Fatalf("short view body: %d", len(body))
	}
	return int(binary.LittleEndian.Uint16(body[1:3]))
}

func TestHandleViewUsesRawAtFineZoom(t *testing.T) {
	s := newViewTestServer(t, 1000)
	req := httptest.NewRequest(http.MethodGet, "/api/view?from=0.01&to=0.02&width=1000", nil)
	rec := httptest.NewRecorder()
	s.handleView(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if got := rec.Header().Get("X-HIL-Source"); got != "raw" {
		t.Fatalf("source=%q want raw", got)
	}
	if got := rec.Body.Bytes()[0]; got != 255 {
		t.Fatalf("tier byte=%d want 255", got)
	}
	if n := viewCount(t, rec.Body.Bytes()); n != 101 {
		t.Fatalf("columns=%d want 101 full-rate points", n)
	}
}

func TestHandleViewUsesTierAtWideZoomAndNeverReturnsEmptyTransition(t *testing.T) {
	s := newViewTestServer(t, 20000)
	for _, width := range []int{500, 1000, 2000, 4000} {
		url := "/api/view?from=0&to=1.9&width=" + strconv.Itoa(width)
		rec := httptest.NewRecorder()
		s.handleView(rec, httptest.NewRequest(http.MethodGet, url, nil))
		if rec.Code != http.StatusOK {
			t.Fatalf("width=%d status=%d", width, rec.Code)
		}
		if n := viewCount(t, rec.Body.Bytes()); n == 0 {
			t.Fatalf("width=%d returned empty view", width)
		}
	}
}

func TestHandleViewRejectsInvalidViewport(t *testing.T) {
	s := newViewTestServer(t, 1)
	for _, url := range []string{
		"/api/view?from=2&to=1&width=800",
		"/api/view?from=0&to=1&width=0",
		"/api/view?from=0&to=1&width=20001",
	} {
		rec := httptest.NewRecorder()
		s.handleView(rec, httptest.NewRequest(http.MethodGet, url, nil))
		if rec.Code != http.StatusBadRequest {
			t.Fatalf("%s status=%d want 400", url, rec.Code)
		}
	}
}
