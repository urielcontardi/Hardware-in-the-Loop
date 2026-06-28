package main

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/record"
)

// buildMinimalHilbin constructs a minimal valid hilbin with the given extra JSON fields.
func buildMinimalHilbin(extra map[string]any) []byte {
	meta := map[string]any{
		"version": 2, "date": "2026-01-01T00:00:00Z",
		"name": "test", "sample_count": 0, "pwm_count": 0,
	}
	for k, v := range extra {
		meta[k] = v
	}
	metaJSON, _ := json.Marshal(meta)
	aligned := (12 + len(metaJSON) + 7) &^ 7
	buf := make([]byte, aligned+8) // space for sample_count(4) + pwm_count(4)
	copy(buf[:7], "HILDATA")
	buf[7] = 1
	binary.LittleEndian.PutUint32(buf[8:12], uint32(len(metaJSON)))
	copy(buf[12:], metaJSON)
	return buf
}

func TestHandleRunsLatestSourceMergesMetadata(t *testing.T) {
	recDir := t.TempDir()
	runsDir := t.TempDir()

	rec := record.New(recDir)
	defer rec.Close()
	if _, err := rec.Start("rawcap"); err != nil {
		t.Fatal(err)
	}
	rec.Submit([]frame.Sample{{TCycles: 10, Epoch: 1, Ia: 1}})
	if err := rec.Stop(); err != nil {
		t.Fatal(err)
	}

	s := &server{runsDir: runsDir, recorder: rec}
	body := buildMinimalHilbin(map[string]any{
		"batch":    map[string]any{"name": "mybatch", "index": float64(1), "count": float64(2)},
		"scenario": map[string]any{"name": "sc1"},
	})
	req := httptest.NewRequest(http.MethodPost, "/api/runs?name=run1.hilbin&source=latest", bytes.NewReader(body))
	rw := httptest.NewRecorder()
	s.handleRuns(rw, req)
	if rw.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rw.Code, rw.Body.String())
	}

	data, err := os.ReadFile(filepath.Join(runsDir, "run1.hilbin"))
	if err != nil {
		t.Fatal(err)
	}
	jsonSize := int(binary.LittleEndian.Uint32(data[8:12]))
	var meta map[string]any
	if err := json.Unmarshal(data[12:12+jsonSize], &meta); err != nil {
		t.Fatal(err)
	}
	batch, ok := meta["batch"].(map[string]any)
	if !ok || batch["name"] != "mybatch" {
		t.Fatalf("batch not merged: %#v", meta)
	}
	sc, ok := meta["scenario"].(map[string]any)
	if !ok || sc["name"] != "sc1" {
		t.Fatalf("scenario not merged: %#v", meta)
	}
	// recorder-owned field must be preserved
	if raw, _ := meta["raw"].(bool); !raw {
		t.Fatalf("raw must stay true: %#v", meta)
	}
}

func TestHandleRunsDisplaySourceUsesUploadedBytes(t *testing.T) {
	dir := t.TempDir()
	s := &server{runsDir: dir}
	want := []byte("displayed-hilbin")
	req := httptest.NewRequest(http.MethodPost, "/api/runs?name=loaded.hilbin&source=display", bytes.NewReader(want))
	rec := httptest.NewRecorder()
	s.handleRuns(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	got, err := os.ReadFile(filepath.Join(dir, "loaded.hilbin"))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, want) {
		t.Fatalf("saved bytes=%q want %q", got, want)
	}
}
