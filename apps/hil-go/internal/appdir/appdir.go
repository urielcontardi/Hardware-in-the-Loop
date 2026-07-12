// Package appdir resolves a writable directory for run recordings that
// works regardless of the current working directory at launch. A relative
// path like "./runs" only works by accident: it depends on the process
// being started from a directory that happens to be writable, which holds
// for the systemd/Docker gateway deployment (only because HIL_RUNS_DIR is
// always set there) but not for a packaged desktop app, where the OS
// launcher may set the working directory to the app bundle itself
// (read-only once signed, e.g. macOS .app) or to Program Files on Windows.
package appdir

import (
	"os"
	"path/filepath"
	"strings"
)

// DefaultRunsDir returns, in priority order: the HIL_RUNS_DIR environment
// variable (unchanged from before — this is what the production Docker
// deployment sets explicitly, so that behavior is preserved exactly); an
// OS-conventional per-user config directory (~/Library/Application
// Support on macOS, %AppData% on Windows, $XDG_CONFIG_HOME or ~/.config on
// Linux); the user's home directory as a further fallback; and only as a
// last resort — if none of the above can be resolved — the historical
// relative "./runs".
func DefaultRunsDir() string {
	if v := strings.TrimSpace(os.Getenv("HIL_RUNS_DIR")); v != "" {
		return v
	}
	if dir, err := os.UserConfigDir(); err == nil {
		return filepath.Join(dir, "HIL Monitor", "runs")
	}
	if home, err := os.UserHomeDir(); err == nil {
		return filepath.Join(home, ".hil-monitor", "runs")
	}
	return "./runs"
}
