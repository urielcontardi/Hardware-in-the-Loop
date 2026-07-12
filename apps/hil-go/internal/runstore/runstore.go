// Package runstore lists, reads, writes and deletes saved .hilbin run files
// in a directory. Ported from cmd/gateway/main.go's handleRuns/
// handleRunsDownload (and their RunMeta/readHilbinMeta helpers) so the
// native app's History tab can browse the same run files the gateway does,
// without a running HTTP server. The gateway file is left untouched.
package runstore

import (
	"encoding/binary"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// RunMeta describes a saved .hilbin run file.
type RunMeta struct {
	Name     string         `json:"name"`
	Size     int64          `json:"size"`
	Modified string         `json:"modified"`
	Meta     map[string]any `json:"meta,omitempty"`
}

var errInvalidName = errors.New("invalid or missing name parameter")

// validName mirrors the gateway's inline checks in handleRuns/handleRunsDownload.
func validName(name string) (string, error) {
	name = strings.TrimSpace(name)
	if name == "" || strings.ContainsAny(name, "/\\") || strings.Contains(name, "..") {
		return "", errInvalidName
	}
	if !strings.HasSuffix(name, ".hilbin") {
		name += ".hilbin"
	}
	return name, nil
}

// List returns every *.hilbin file in dir, newest first, mirroring
// cmd/gateway/main.go's handleRuns GET.
func List(dir string) ([]RunMeta, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return []RunMeta{}, nil
	}
	var runs []RunMeta
	for _, e := range entries {
		if !strings.HasSuffix(e.Name(), ".hilbin") {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		runs = append(runs, RunMeta{
			Name:     e.Name(),
			Size:     info.Size(),
			Modified: info.ModTime().UTC().Format(time.RFC3339),
			Meta:     ReadMeta(filepath.Join(dir, e.Name())),
		})
	}
	sort.Slice(runs, func(i, j int) bool { return runs[i].Modified > runs[j].Modified })
	if runs == nil {
		runs = []RunMeta{}
	}
	return runs, nil
}

// Save writes data as dir/name (name is sanitized against path traversal and
// gains a .hilbin suffix if missing), mirroring the fallback branch of the
// gateway's handleRuns POST (used when CopyLatest didn't claim the file).
func Save(dir, name string, data []byte) (RunMeta, error) {
	clean, err := validName(name)
	if err != nil {
		return RunMeta{}, err
	}
	path := filepath.Join(dir, filepath.Base(clean))
	if err := os.WriteFile(path, data, 0644); err != nil {
		return RunMeta{}, err
	}
	fi, err := os.Stat(path)
	if err != nil {
		return RunMeta{}, err
	}
	return RunMeta{Name: clean, Size: fi.Size(), Modified: fi.ModTime().UTC().Format(time.RFC3339)}, nil
}

// Read returns the raw bytes of dir/name, mirroring the gateway's
// handleRunsDownload GET.
func Read(dir, name string) ([]byte, error) {
	clean, err := validName(name)
	if err != nil {
		return nil, err
	}
	return os.ReadFile(filepath.Join(dir, filepath.Base(clean)))
}

// Delete removes dir/name, mirroring the gateway's handleRunsDownload DELETE.
func Delete(dir, name string) error {
	clean, err := validName(name)
	if err != nil {
		return err
	}
	return os.Remove(filepath.Join(dir, filepath.Base(clean)))
}

// ReadMetaFromBytes extracts the JSON metadata header from an in-memory
// .hilbin buffer, mirroring cmd/gateway/main.go's readHilbinMetaFromBytes.
func ReadMetaFromBytes(data []byte) map[string]any {
	if len(data) < 12 || string(data[:7]) != "HILDATA" {
		return nil
	}
	jsonSize := int(binary.LittleEndian.Uint32(data[8:12]))
	if jsonSize <= 0 || jsonSize > 1<<20 || 12+jsonSize > len(data) {
		return nil
	}
	var meta map[string]any
	if err := json.Unmarshal(data[12:12+jsonSize], &meta); err != nil {
		return nil
	}
	return meta
}

// ReadMeta extracts the JSON metadata header from a .hilbin file on disk,
// mirroring cmd/gateway/main.go's readHilbinMeta.
func ReadMeta(path string) map[string]any {
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()

	header := make([]byte, 12)
	if _, err := io.ReadFull(f, header); err != nil {
		return nil
	}
	if string(header[:7]) != "HILDATA" {
		return nil
	}
	jsonSize := int(uint32(header[8]) | uint32(header[9])<<8 | uint32(header[10])<<16 | uint32(header[11])<<24)
	if jsonSize <= 0 || jsonSize > 1<<20 {
		return nil
	}
	buf := make([]byte, jsonSize)
	if _, err := io.ReadFull(f, buf); err != nil {
		return nil
	}
	var meta map[string]any
	if err := json.Unmarshal(buf, &meta); err != nil {
		return nil
	}
	return meta
}
