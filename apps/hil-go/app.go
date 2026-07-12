package main

import (
	"context"
	"encoding/base64"
	"errors"
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/wailsapp/wails/v2/pkg/runtime"

	"hil.local/daemon/internal/appdir"
	"hil.local/daemon/internal/derive"
	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/pwmrecv"
	"hil.local/daemon/internal/pyramid"
	"hil.local/daemon/internal/rawbuf"
	"hil.local/daemon/internal/receiver"
	"hil.local/daemon/internal/record"
	"hil.local/daemon/internal/ring"
	"hil.local/daemon/internal/runstore"
	"hil.local/daemon/internal/sampleclock"
	"hil.local/daemon/internal/sessionstore"
	hilUDP "hil.local/daemon/internal/udp"
	"hil.local/daemon/internal/viewquery"
)

// drainDelay gives in-flight UDP telemetry/PWM packets time to arrive before
// a capture file is sealed. Mirrors cmd/gateway/main.go's handleStop/handleReset,
// which rely on this same delay so the native app captures the same tail of
// data the gateway does.
const drainDelay = 80 * time.Millisecond

var errStoreUnavailable = errors.New("session store not available")

type App struct {
	ctx     context.Context
	recv    *receiver.Receiver
	pwmRecv *pwmrecv.Receiver
	ring    *ring.Ring
	localIP string
	done    chan struct{}

	stateMu   sync.Mutex
	lastSet   map[string]hilUDP.SetParams
	lastMotor map[string]hilUDP.MotorParams
	recorder  *record.Recorder
	raw       *rawbuf.Buffer

	// runsDir, pyramid and store back the same historical-viewport contract
	// the gateway's /api/view and /api/tiers serve (see internal/viewquery),
	// so a run of any length stays fully visible instead of sliding off the
	// ~6s raw buffer window.
	runsDir  string
	ingestMu sync.Mutex
	clk      sampleclock.Clock
	pyramid  *pyramid.Pyramid
	store    *sessionstore.Store
	motor    derive.Motor
}

// Keep the native app on the same acquisition and display contract as the
// gateway: about 100 ksample/s from DMA, reduced only for the UI.
const (
	transportDecim = 77
	solverClockHz  = 200_000_000
	solverStep     = 26
	dmaTelemetryHz = solverClockHz / solverStep / transportDecim
	gpioFallbackHz = 10000
	telemetryPort  = 5006
	pwmEventsPort  = 5007
)

func NewApp() *App {
	runsDir := appdir.DefaultRunsDir()
	a := &App{
		ring:      ring.New(262144),
		done:      make(chan struct{}),
		lastSet:   make(map[string]hilUDP.SetParams),
		lastMotor: make(map[string]hilUDP.MotorParams),
		recorder:  record.New(runsDir),
		raw:       rawbuf.New(300_000),
		runsDir:   runsDir,
		pyramid:   pyramid.New(dmaTelemetryHz),
		motor:     derive.DefaultMotor,
	}
	a.resetSession()
	return a
}

func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
	a.localIP = hilUDP.LocalIP()

	recv := receiver.New(telemetryPort, a.ring)
	if err := recv.Start(); err != nil {
		runtime.LogErrorf(ctx, "receiver: %v", err)
		return
	}
	a.recv = recv
	recv.SetSampleHandler(func(samples []frame.Sample) {
		a.recorder.Submit(samples)
		a.raw.Append(samples)
		a.ingestSamples(samples)
	})

	pwmRecv := pwmrecv.New(pwmEventsPort)
	if err := pwmRecv.Start(); err != nil {
		runtime.LogErrorf(ctx, "pwm receiver: %v", err)
	} else {
		a.pwmRecv = pwmRecv
	}

	go a.broadcastLoop()
	runtime.LogInfof(ctx, "HIL daemon ready — telem destination: %s", a.localIP)
}

func (a *App) shutdown(_ context.Context) {
	close(a.done)
	if a.recv != nil {
		a.recv.Stop()
	}
	if a.pwmRecv != nil {
		a.pwmRecv.Stop()
	}
	if a.recorder != nil {
		_ = a.recorder.Close()
	}
	a.ingestMu.Lock()
	if a.store != nil {
		_ = a.store.Close()
	}
	a.ingestMu.Unlock()
}

// ingestSamples feeds the pyramid+session store pair that backs
// GetHistoricalView/GetTiersInfo, mirroring cmd/gateway/main.go's telemetry
// SetSampleHandler. Runs on the receiver's single goroutine, same as the
// gateway's ingestion path.
func (a *App) ingestSamples(samples []frame.Sample) {
	a.ingestMu.Lock()
	defer a.ingestMu.Unlock()
	if a.store == nil {
		return
	}
	motor := a.motor
	for _, smp := range samples {
		if a.clk.HaveEpoch && smp.Epoch != a.clk.Epoch {
			a.resetSessionLocked()
		}
		t, ok := a.clk.Seconds(smp.TCycles, smp.Epoch)
		if !ok {
			continue
		}
		a.store.Append(t, smp)
		a.pyramid.Push(t, motor.Compute(smp).Values())
	}
}

// resetSession closes the current full-rate session file and opens a fresh
// one, mirroring cmd/gateway/main.go's resetSession (called on Attach/Run so
// old samples never bleed into a new run's view).
func (a *App) resetSession() {
	a.ingestMu.Lock()
	defer a.ingestMu.Unlock()
	a.resetSessionLocked()
}

func (a *App) resetSessionLocked() {
	if a.store != nil {
		_ = a.store.Close()
	}
	st, err := sessionstore.Open(filepath.Join(a.runsDir, "live_session.bin"), 4096)
	if err != nil {
		log.Printf("session store reopen: %v", err)
		return
	}
	st.SetMaxSamples(180_000_000)
	a.store = st
	if a.pyramid != nil {
		a.pyramid.Reset()
	}
	a.clk = sampleclock.Clock{}
}

func (a *App) setMotor(m derive.Motor) {
	a.ingestMu.Lock()
	a.motor = m
	a.ingestMu.Unlock()
}

// GetHistoricalView answers a viewport query the same way the gateway's
// GET /api/view does, returning the base64-encoded tile wire format
// frontend/src/tile.ts decodes (Wails IPC has no raw-binary transport).
func (a *App) GetHistoricalView(from, to float64, width int) (string, error) {
	a.ingestMu.Lock()
	pyr, store, motor := a.pyramid, a.store, a.motor
	a.ingestMu.Unlock()
	if pyr == nil || store == nil {
		return "", errStoreUnavailable
	}
	view, err := viewquery.BuildView(pyr, store, motor, from, to, width)
	if err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(viewquery.Encode(view)), nil
}

// GetTiersInfo answers the same session-span/sample-count query as the
// gateway's GET /api/tiers.
func (a *App) GetTiersInfo() (viewquery.TiersMeta, error) {
	a.ingestMu.Lock()
	pyr, store := a.pyramid, a.store
	a.ingestMu.Unlock()
	if pyr == nil {
		return viewquery.TiersMeta{}, errStoreUnavailable
	}
	return viewquery.BuildTiersMeta(pyr, store), nil
}

func (a *App) broadcastLoop() {
	ticker := time.NewTicker(16 * time.Millisecond)
	defer ticker.Stop()
	scratch := make([]frame.Sample, 4096)

	for {
		select {
		case <-a.done:
			return
		case b := <-a.pwmRecv.C:
			a.recorder.SubmitPWM(b.ClockHz, b.Events)
			runtime.EventsEmit(a.ctx, "pwm_events", b)
		case <-ticker.C:
			n := a.ring.PopN(scratch)
			if n > 0 {
				batch := append([]frame.Sample(nil), scratch[:n]...)
				if len(batch) > 0 {
					runtime.EventsEmit(a.ctx, "telemetry", batch)
				}
			}
		}
	}
}

// ProgramMotor computes TIM matrices on the PS and writes them to the FPGA.
func (a *App) ProgramMotor(ip string, rs, rr, ls, lr, lm, j, npp float32) (*hilUDP.HilStatus, error) {
	p := hilUDP.MotorParams{
		Rs: &rs, Rr: &rr, Ls: &ls, Lr: &lr, Lm: &lm, J: &j, Npp: &npp,
	}
	status, err := hilUDP.ProgramMotor(ip, p)
	if err == nil {
		a.stateMu.Lock()
		a.lastMotor[ip] = p
		a.stateMu.Unlock()
		a.setMotor(derive.MotorFromParams(p.Npp, p.Lm, p.Lr))
	}
	return status, err
}

// SetParams sends control parameters to the PS board.
// Empty/zero "do not change" semantics are encoded via the includeXxx flags
// so the user can update just a subset of params.
func (a *App) SetParams(
	ip string,
	freqHz, vdcV, torqueNm float32,
	baseFreqHz, maxVPu, accelTimeSec float32,
	enable bool, applyEnable bool,
	attachTelem bool,
) (*hilUDP.HilStatus, error) {
	p := hilUDP.SetParams{
		FreqHz:       &freqHz,
		VdcV:         &vdcV,
		TorqueNm:     &torqueNm,
		BaseFreqHz:   &baseFreqHz,
		MaxVPu:       &maxVPu,
		AccelTimeSec: &accelTimeSec,
	}
	if applyEnable {
		en := 0
		if enable {
			en = 1
		}
		p.Enable = &en
	}
	if attachTelem {
		p.TelemDst = a.localIP
		decim := transportDecim
		sampleHz := uint32(gpioFallbackHz)
		p.Decim = &decim
		p.TelemHz = &sampleHz
		if a.ring != nil {
			a.ring.Clear()
		}
		a.raw.Reset()
		a.resetSession()
		a.punchTelemetry(ip)
	}
	status, err := hilUDP.Set(ip, p)
	if err == nil {
		a.stateMu.Lock()
		a.lastSet[ip] = p
		a.stateMu.Unlock()
		if attachTelem {
			a.punchTelemetry(ip)
		}
	}
	return status, err
}

func (a *App) GetRawTelemetry(cursor uint64, limit int) string {
	if limit <= 0 || limit > 20_000 {
		limit = 20_000
	}
	return base64.StdEncoding.EncodeToString(rawbuf.Encode(a.raw.Since(cursor, limit)))
}

// GetStatus polls the current controller state from the PS board.
func (a *App) GetStatus(ip string) (*hilUDP.HilStatus, error) {
	return hilUDP.Get(ip)
}

// punchTelemetry sends a tiny outbound packet from both UDP receivers to the
// board. Mirrors cmd/gateway/main.go's Punch calls: it keeps stateful
// firewalls/NATs open for the reverse telemetry/PWM stream so the board's
// unsolicited UDP packets are accepted back in.
func (a *App) punchTelemetry(ip string) {
	if a.recv != nil {
		a.recv.Punch(ip, telemetryPort)
	}
	if a.pwmRecv != nil {
		a.pwmRecv.Punch(ip, pwmEventsPort)
	}
}

// Run enables the motor with the last-applied params.
func (a *App) Run(ip string) (*hilUDP.HilStatus, error) {
	if a.ring != nil {
		a.ring.Clear()
	}
	a.raw.Reset()
	a.resetSession()
	a.punchTelemetry(ip)
	if _, err := a.recorder.Start(""); err != nil {
		return nil, err
	}
	status, err := hilUDP.Run(ip)
	if err == nil {
		a.recorder.SetMetadata(a.captureMetadata(ip, status))
		a.punchTelemetry(ip)
		return status, nil
	}
	if !strings.Contains(err.Error(), `command "run" was not retried`) {
		_ = a.recorder.Stop()
		return status, err
	}

	a.stateMu.Lock()
	motor, hasMotor := a.lastMotor[ip]
	params, hasParams := a.lastSet[ip]
	a.stateMu.Unlock()

	if hasMotor {
		if _, motorErr := hilUDP.ProgramMotor(ip, motor); motorErr != nil {
			_ = a.recorder.Stop()
			return nil, motorErr
		}
	}
	if hasParams {
		if _, setErr := hilUDP.Set(ip, params); setErr != nil {
			_ = a.recorder.Stop()
			return nil, setErr
		}
	}
	status, err = hilUDP.Run(ip)
	if err != nil {
		_ = a.recorder.Stop()
	} else {
		a.recorder.SetMetadata(a.captureMetadata(ip, status))
		a.punchTelemetry(ip)
	}
	return status, err
}

// captureMetadata mirrors cmd/gateway/main.go's captureMetadata: the
// controller/motor snapshot embedded in every raw capture the recorder
// seals, so History entries carry the same setup summary the gateway's do.
func (a *App) captureMetadata(ip string, status *hilUDP.HilStatus) map[string]any {
	controller := map[string]any{}
	if status != nil {
		controller = map[string]any{
			"freq_hz":        status.FreqHz,
			"freq_actual_hz": status.FreqActualHz,
			"vdc_v":          status.VdcV,
			"torque_nm":      status.TorqueNm,
			"base_freq_hz":   status.BaseFreqHz,
			"max_v_pu":       status.MaxVPu,
			"accel_time_s":   status.AccelTimeSec,
		}
	}

	a.stateMu.Lock()
	motor := a.lastMotor[ip]
	a.stateMu.Unlock()

	return map[string]any{
		"controller": controller,
		"motor": map[string]any{
			"rs":  ptrValue(motor.Rs, 0.4396),
			"rr":  ptrValue(motor.Rr, 0.2826),
			"ls":  ptrValue(motor.Ls, 3.1364e-3),
			"lr":  ptrValue(motor.Lr, 6.3264e-3),
			"lm":  ptrValue(motor.Lm, 109.9442e-3),
			"j":   ptrValue(motor.J, 0.4),
			"npp": ptrValue(motor.Npp, 2.0),
		},
	}
}

func ptrValue(p *float32, fallback float32) float32 {
	if p == nil {
		return fallback
	}
	return *p
}

// ListRuns returns every saved .hilbin run, mirroring GET /api/runs.
func (a *App) ListRuns() ([]runstore.RunMeta, error) {
	return runstore.List(a.runsDir)
}

// SaveRunToHistory registers a run in the browsable History list, mirroring
// POST /api/runs: when source != "display" it first tries to claim the
// just-sealed full-rate raw capture (record.Recorder.CopyLatest) instead of
// the browser-buffered bytes, same as the gateway.
func (a *App) SaveRunToHistory(dataB64, name, source string) (runstore.RunMeta, error) {
	data, err := base64.StdEncoding.DecodeString(dataB64)
	if err != nil {
		return runstore.RunMeta{}, err
	}
	clean := name
	if !strings.HasSuffix(clean, ".hilbin") {
		clean += ".hilbin"
	}
	if source != "display" {
		path := filepath.Join(a.runsDir, filepath.Base(clean))
		extra := runstore.ReadMetaFromBytes(data)
		if copied, copyErr := a.recorder.CopyLatest(path, extra); copyErr != nil {
			return runstore.RunMeta{}, copyErr
		} else if copied {
			fi, statErr := os.Stat(path)
			if statErr != nil {
				return runstore.RunMeta{}, statErr
			}
			return runstore.RunMeta{Name: filepath.Base(clean), Size: fi.Size(), Modified: fi.ModTime().UTC().Format(time.RFC3339)}, nil
		}
	}
	return runstore.Save(a.runsDir, clean, data)
}

// DownloadRun returns a saved run's base64-encoded bytes, mirroring
// GET /api/runs/{name} (Wails IPC has no raw-binary transport).
func (a *App) DownloadRun(name string) (string, error) {
	data, err := runstore.Read(a.runsDir, name)
	if err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(data), nil
}

// DeleteRun removes a saved run from disk, mirroring DELETE /api/runs/{name}.
func (a *App) DeleteRun(name string) error {
	return runstore.Delete(a.runsDir, name)
}

// Pause disables the motor but keeps the params.
func (a *App) Pause(ip string) (*hilUDP.HilStatus, error) {
	return hilUDP.Pause(ip)
}

// StopController disables the motor and resets params to safe defaults.
// The PS daemon stays alive.
//
// Order mirrors cmd/gateway/main.go's handleStop: send Stop, then drain
// in-flight UDP telemetry and punch the PWM receiver so the board flushes
// its accumulated PWM FIFO, and only then seal the recorder. Sealing the
// recorder before that drain (the previous behavior here) silently dropped
// the last ~160ms of telemetry and the tail of PWM events on every stop.
func (a *App) StopController(ip string) (*hilUDP.HilStatus, error) {
	status, err := hilUDP.Stop(ip)
	time.Sleep(drainDelay)
	if a.pwmRecv != nil {
		a.pwmRecv.Punch(ip, pwmEventsPort)
	}
	time.Sleep(drainDelay)
	if stopErr := a.recorder.Stop(); err == nil && stopErr != nil {
		err = stopErr
	}
	_, _ = hilUDP.TelemOff(ip)
	if a.ring != nil {
		a.ring.Clear()
	}
	return status, err
}

// ResetSolver clears the FPGA TIM_Solver integrator states. Used between
// runs when the previous experiment left the rotor flux/speed in a state
// that masks the new excitation. Drains and seals the recorder the same way
// StopController does (mirrors cmd/gateway/main.go's handleReset) since a
// reset also ends the current capture.
func (a *App) ResetSolver(ip string) (*hilUDP.HilStatus, error) {
	status, err := hilUDP.ResetSolver(ip)
	time.Sleep(drainDelay)
	if a.pwmRecv != nil {
		a.pwmRecv.Punch(ip, pwmEventsPort)
	}
	time.Sleep(drainDelay)
	if stopErr := a.recorder.Stop(); err == nil && stopErr != nil {
		err = stopErr
	}
	return status, err
}

// AttachTelemetry tells the board to push telemetry to this PC.
func (a *App) AttachTelemetry(ip string) (*hilUDP.HilStatus, error) {
	if a.ring != nil {
		a.ring.Clear()
	}
	a.raw.Reset()
	a.resetSession()
	a.punchTelemetry(ip)
	decim := transportDecim
	sampleHz := uint32(gpioFallbackHz)
	status, err := hilUDP.Set(ip, hilUDP.SetParams{Decim: &decim, TelemHz: &sampleHz, TelemDst: a.localIP})
	if err != nil {
		return status, err
	}
	a.punchTelemetry(ip)
	return status, err
}

// Ping is a quick health check.
func (a *App) Ping(ip string) (*hilUDP.HilStatus, error) {
	return hilUDP.Ping(ip)
}

// ShutdownBoard kills the PS daemon (rare).
func (a *App) ShutdownBoard(ip string) (*hilUDP.HilStatus, error) {
	return hilUDP.Shutdown(ip)
}

// DiscoverBoard sends a one-shot UDP broadcast and returns the first board found.
func (a *App) DiscoverBoard() (*hilUDP.DiscoveryResponse, error) {
	return hilUDP.Discover(1200 * time.Millisecond)
}

// GetStats returns receiver statistics.
func boolToUint64(v bool) uint64 {
	if v {
		return 1
	}
	return 0
}

func (a *App) GetStats() map[string]uint64 {
	if a.recv == nil {
		return map[string]uint64{}
	}
	recording, recordWritten, recordDropped := a.recorder.Stats()
	return map[string]uint64{
		"packets_raw":    a.recv.Stats.PacketsRaw.Load(),
		"samples_rx":     a.recv.Stats.SamplesRx.Load(),
		"packets_rx":     a.recv.Stats.PacketsRx.Load(),
		"dropped":        a.recv.Stats.Dropped.Load(),
		"crc_errors":     a.recv.Stats.CRCErrors.Load(),
		"invalid":        a.recv.Stats.Invalid.Load(),
		"seq_missed":     a.recv.Stats.SeqMissed.Load(),
		"ring_len":       uint64(a.ring.Len()),
		"recording":      boolToUint64(recording),
		"record_written": recordWritten,
		"record_dropped": recordDropped,
		"pwm_packets_rx": func() uint64 {
			if a.pwmRecv != nil {
				return a.pwmRecv.Stats.PacketsRx.Load()
			}
			return 0
		}(),
		"pwm_events_rx": func() uint64 {
			if a.pwmRecv != nil {
				return a.pwmRecv.Stats.EventsRx.Load()
			}
			return 0
		}(),
	}
}

// GetLocalIP returns the machine's primary non-loopback IPv4 address.
func (a *App) GetLocalIP() string {
	return a.localIP
}

// SaveRun opens a native save dialog and writes the provided base64-encoded
// .hilbin data to the chosen path.
func (a *App) SaveRun(dataB64 string, suggestedName string) error {
	path, err := runtime.SaveFileDialog(a.ctx, runtime.SaveDialogOptions{
		DefaultFilename: suggestedName,
		Filters: []runtime.FileFilter{
			{DisplayName: "HIL Run (*.hilbin)", Pattern: "*.hilbin"},
		},
	})
	if err != nil || path == "" {
		return err
	}
	if copied, copyErr := a.recorder.CopyLatest(path, nil); copyErr != nil {
		return copyErr
	} else if copied {
		return nil
	}
	data, err := base64.StdEncoding.DecodeString(dataB64)
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0644)
}

// LoadRun opens a native open dialog and returns the chosen file's contents
// as a base64-encoded string.
func (a *App) LoadRun() (string, error) {
	path, err := runtime.OpenFileDialog(a.ctx, runtime.OpenDialogOptions{
		Filters: []runtime.FileFilter{
			{DisplayName: "HIL Run (*.hilbin)", Pattern: "*.hilbin"},
		},
	})
	if err != nil || path == "" {
		return "", err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(data), nil
}
