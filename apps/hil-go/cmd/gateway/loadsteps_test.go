package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/sessionstore"
)

func TestLoadStepsFollowSessionTimeAndReset(t *testing.T) {
	st, err := sessionstore.Open(filepath.Join(t.TempDir(), "live.bin"), 2)
	if err != nil {
		t.Fatal(err)
	}
	defer st.Close()
	s := &server{store: st}
	s.recordLoadCommand(5)
	st.Append(2.0, frame.Sample{})
	s.recordLoadCommand(15)

	rec := httptest.NewRecorder()
	s.handleLoadSteps(rec, httptest.NewRequest(http.MethodGet, "/api/load-steps", nil))
	var got []loadStep
	if err := json.Unmarshal(rec.Body.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || got[0] != (loadStep{T: 0, Value: 5}) || got[1] != (loadStep{T: 2, Value: 15}) {
		t.Fatalf("steps=%v", got)
	}

	s.pyramid = newTestServer().pyramid
	s.runsDir = t.TempDir()
	s.resetSession()
	if len(s.loadSteps) != 1 || s.loadSteps[0] != (loadStep{T: 0, Value: 15}) {
		t.Fatalf("reset steps=%v", s.loadSteps)
	}
}
