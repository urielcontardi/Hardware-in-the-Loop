package runstore

import (
	"encoding/binary"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func hilbinBytes(t *testing.T, meta map[string]any, payload []byte) []byte {
	t.Helper()
	metaBytes := []byte(`{"name":"x"}`)
	if meta != nil {
		b, err := json.Marshal(meta)
		if err != nil {
			t.Fatal(err)
		}
		metaBytes = b
	}
	header := make([]byte, 12)
	copy(header, "HILDATA")
	header[7] = 1
	binary.LittleEndian.PutUint32(header[8:], uint32(len(metaBytes)))
	out := append(header, metaBytes...)
	out = append(out, payload...)
	return out
}

func TestSaveListReadDelete(t *testing.T) {
	dir := t.TempDir()

	meta, err := Save(dir, "hil_run_test", hilbinBytes(t, map[string]any{"scenario": "s1"}, []byte("payload")))
	if err != nil {
		t.Fatalf("Save: %v", err)
	}
	if meta.Name != "hil_run_test.hilbin" {
		t.Fatalf("Name=%q want suffix appended", meta.Name)
	}

	runs, err := List(dir)
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(runs) != 1 || runs[0].Name != "hil_run_test.hilbin" {
		t.Fatalf("runs=%+v", runs)
	}
	if runs[0].Meta["scenario"] != "s1" {
		t.Fatalf("meta not parsed: %+v", runs[0].Meta)
	}

	data, err := Read(dir, "hil_run_test.hilbin")
	if err != nil {
		t.Fatalf("Read: %v", err)
	}
	if len(data) == 0 {
		t.Fatal("Read returned empty data")
	}

	if err := Delete(dir, "hil_run_test.hilbin"); err != nil {
		t.Fatalf("Delete: %v", err)
	}
	runs, _ = List(dir)
	if len(runs) != 0 {
		t.Fatalf("runs after delete=%+v, want empty", runs)
	}
}

func TestSaveAppendsHilbinSuffix(t *testing.T) {
	dir := t.TempDir()
	meta, err := Save(dir, "noext", []byte("x"))
	if err != nil {
		t.Fatalf("Save: %v", err)
	}
	if meta.Name != "noext.hilbin" {
		t.Fatalf("Name=%q want noext.hilbin", meta.Name)
	}
}

func TestRejectsPathTraversal(t *testing.T) {
	dir := t.TempDir()
	for _, name := range []string{"../escape", "sub/dir", "a\\b", "", "  "} {
		if _, err := Save(dir, name, []byte("x")); err == nil {
			t.Fatalf("Save(%q): want error", name)
		}
		if _, err := Read(dir, name); err == nil {
			t.Fatalf("Read(%q): want error", name)
		}
		if err := Delete(dir, name); err == nil {
			t.Fatalf("Delete(%q): want error", name)
		}
	}
}

func TestListSortsNewestFirst(t *testing.T) {
	dir := t.TempDir()
	older := filepath.Join(dir, "a.hilbin")
	newer := filepath.Join(dir, "b.hilbin")
	if err := os.WriteFile(older, []byte("x"), 0644); err != nil {
		t.Fatal(err)
	}
	oldTime := time.Now().Add(-time.Hour)
	if err := os.Chtimes(older, oldTime, oldTime); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(newer, []byte("y"), 0644); err != nil {
		t.Fatal(err)
	}

	runs, err := List(dir)
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(runs) != 2 || runs[0].Name != "b.hilbin" || runs[1].Name != "a.hilbin" {
		t.Fatalf("runs=%+v, want [b.hilbin, a.hilbin]", runs)
	}
}

func TestListOnMissingDirReturnsEmpty(t *testing.T) {
	runs, err := List(filepath.Join(t.TempDir(), "does-not-exist"))
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(runs) != 0 {
		t.Fatalf("runs=%+v, want empty", runs)
	}
}

func TestReadMetaFromBytesAndReadMetaAgree(t *testing.T) {
	data := hilbinBytes(t, map[string]any{"scenario": "s2", "n": 3.0}, []byte("payload"))

	fromBytes := ReadMetaFromBytes(data)
	if fromBytes["scenario"] != "s2" || fromBytes["n"] != 3.0 {
		t.Fatalf("ReadMetaFromBytes=%+v", fromBytes)
	}

	dir := t.TempDir()
	path := filepath.Join(dir, "m.hilbin")
	if err := os.WriteFile(path, data, 0644); err != nil {
		t.Fatal(err)
	}
	fromFile := ReadMeta(path)
	if fromFile["scenario"] != "s2" || fromFile["n"] != 3.0 {
		t.Fatalf("ReadMeta=%+v", fromFile)
	}
}

func TestReadMetaFromBytesRejectsBadMagic(t *testing.T) {
	if got := ReadMetaFromBytes([]byte("not a hilbin file")); got != nil {
		t.Fatalf("got %+v, want nil", got)
	}
}
