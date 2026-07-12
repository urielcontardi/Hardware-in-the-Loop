package appdir

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDefaultRunsDir_EnvVarTakesPriority(t *testing.T) {
	t.Setenv("HIL_RUNS_DIR", "/app/runs")

	got := DefaultRunsDir()

	if got != "/app/runs" {
		t.Errorf("DefaultRunsDir() = %q, want %q (env var must win, unchanged production behavior)", got, "/app/runs")
	}
}

func TestDefaultRunsDir_FallsBackToUserConfigDir(t *testing.T) {
	t.Setenv("HIL_RUNS_DIR", "")

	got := DefaultRunsDir()

	wantDir, err := os.UserConfigDir()
	if err != nil {
		t.Skipf("os.UserConfigDir unavailable in this environment: %v", err)
	}
	want := filepath.Join(wantDir, "HIL Monitor", "runs")
	if got != want {
		t.Errorf("DefaultRunsDir() = %q, want %q", got, want)
	}
	if !filepath.IsAbs(got) {
		t.Errorf("DefaultRunsDir() = %q, want an absolute path (never a bare relative %q)", got, "./runs")
	}
}
