package main

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

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
