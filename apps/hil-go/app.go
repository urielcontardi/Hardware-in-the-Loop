package main

import (
	"context"
	"encoding/base64"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/wailsapp/wails/v2/pkg/runtime"

	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/pwmrecv"
	"hil.local/daemon/internal/rawbuf"
	"hil.local/daemon/internal/receiver"
	"hil.local/daemon/internal/record"
	"hil.local/daemon/internal/ring"
	hilUDP "hil.local/daemon/internal/udp"
)

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
}

// Keep the native app on the same acquisition and display contract as the
// gateway: about 100 ksample/s from DMA, reduced only for the UI.
const (
	transportDecim    = 77
	gpioFallbackHz    = 10000
)

func NewApp() *App {
	return &App{
		ring:      ring.New(262144),
		done:      make(chan struct{}),
		lastSet:   make(map[string]hilUDP.SetParams),
		lastMotor: make(map[string]hilUDP.MotorParams),
		recorder:  record.New("./runs"),
		raw:       rawbuf.New(300_000),
	}
}

func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
	a.localIP = hilUDP.LocalIP()

	recv := receiver.New(5006, a.ring)
	if err := recv.Start(); err != nil {
		runtime.LogErrorf(ctx, "receiver: %v", err)
		return
	}
	a.recv = recv
	recv.SetSampleHandler(func(samples []frame.Sample) {
		a.recorder.Submit(samples)
		a.raw.Append(samples)
	})

	pwmRecv := pwmrecv.New(5007)
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
	}
	status, err := hilUDP.Set(ip, p)
	if err == nil {
		a.stateMu.Lock()
		a.lastSet[ip] = p
		a.stateMu.Unlock()
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

// Run enables the motor with the last-applied params.
func (a *App) Run(ip string) (*hilUDP.HilStatus, error) {
	a.raw.Reset()
	if _, err := a.recorder.Start(""); err != nil {
		return nil, err
	}
	status, err := hilUDP.Run(ip)
	if err == nil {
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
	}
	return status, err
}

// Pause disables the motor but keeps the params.
func (a *App) Pause(ip string) (*hilUDP.HilStatus, error) {
	return hilUDP.Pause(ip)
}

// StopController disables the motor and resets params to safe defaults.
// The PS daemon stays alive.
func (a *App) StopController(ip string) (*hilUDP.HilStatus, error) {
	status, err := hilUDP.Stop(ip)
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
// that masks the new excitation.
func (a *App) ResetSolver(ip string) (*hilUDP.HilStatus, error) {
	return hilUDP.ResetSolver(ip)
}

// AttachTelemetry tells the board to push telemetry to this PC.
func (a *App) AttachTelemetry(ip string) (*hilUDP.HilStatus, error) {
	if a.ring != nil {
		a.ring.Clear()
	}
	decim := transportDecim
	sampleHz := uint32(gpioFallbackHz)
	return hilUDP.Set(ip, hilUDP.SetParams{Decim: &decim, TelemHz: &sampleHz, TelemDst: a.localIP})
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
