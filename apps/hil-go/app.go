package main

import (
	"context"
	"encoding/base64"
	"os"
	"time"

	"github.com/wailsapp/wails/v2/pkg/runtime"

	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/pwmrecv"
	"hil.local/daemon/internal/receiver"
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
}

// transportDecim — FPGA AXI-Stream decimation factor (used when DMA path is
// enabled). 375 → 3.704 MHz / 375 = ~9.876 kHz. The on-chip IIR
// (ALPHA_BITS=9, fc ≈ 1.15 kHz) is the anti-aliasing pre-filter for this rate.
//
// NOTE: As of this commit the PS-side falls back to GPIO polling (10 kHz)
// because the AXI DMA HP-slave path is not cache-coherent with the Cortex-A9
// and userspace lacks the D-cache invalidate primitive needed before each
// buffer read. Proper fix is to re-route AXI DMA to S_AXI_ACP in the Vivado
// design. See src/ps_app/main.c and src/ps_app/dma_telem.c.
const transportDecim = 375

func NewApp() *App {
	return &App{
		ring: ring.New(262144),
		done: make(chan struct{}),
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
			runtime.EventsEmit(a.ctx, "pwm_events", b)
		case <-ticker.C:
			n := a.ring.PopN(scratch)
			if n > 0 {
				batch := append([]frame.Sample(nil), scratch[:n]...)
				runtime.EventsEmit(a.ctx, "telemetry", batch)
			}
		}
	}
}

// ProgramMotor computes TIM matrices on the PS and writes them to the FPGA.
func (a *App) ProgramMotor(ip string, rs, rr, ls, lr, lm, j, npp float32) (*hilUDP.HilStatus, error) {
	p := hilUDP.MotorParams{
		Rs: &rs, Rr: &rr, Ls: &ls, Lr: &lr, Lm: &lm, J: &j, Npp: &npp,
	}
	return hilUDP.ProgramMotor(ip, p)
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
		p.Decim = &decim
	}
	return hilUDP.Set(ip, p)
}

// GetStatus polls the current controller state from the PS board.
func (a *App) GetStatus(ip string) (*hilUDP.HilStatus, error) {
	return hilUDP.Get(ip)
}

// Run enables the motor with the last-applied params.
func (a *App) Run(ip string) (*hilUDP.HilStatus, error) {
	return hilUDP.Run(ip)
}

// Pause disables the motor but keeps the params.
func (a *App) Pause(ip string) (*hilUDP.HilStatus, error) {
	return hilUDP.Pause(ip)
}

// StopController disables the motor and resets params to safe defaults.
// The PS daemon stays alive.
func (a *App) StopController(ip string) (*hilUDP.HilStatus, error) {
	status, err := hilUDP.Stop(ip)
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
	return hilUDP.Set(ip, hilUDP.SetParams{Decim: &decim, TelemDst: a.localIP})
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
func (a *App) GetStats() map[string]uint64 {
	if a.recv == nil {
		return map[string]uint64{}
	}
	return map[string]uint64{
		"packets_raw": a.recv.Stats.PacketsRaw.Load(),
		"samples_rx":  a.recv.Stats.SamplesRx.Load(),
		"packets_rx":  a.recv.Stats.PacketsRx.Load(),
		"dropped":     a.recv.Stats.Dropped.Load(),
		"crc_errors":  a.recv.Stats.CRCErrors.Load(),
		"invalid":     a.recv.Stats.Invalid.Load(),
		"seq_missed":  a.recv.Stats.SeqMissed.Load(),
		"ring_len":    uint64(a.ring.Len()),
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
	data, err := base64.StdEncoding.DecodeString(dataB64)
	if err != nil {
		return err
	}
	path, err := runtime.SaveFileDialog(a.ctx, runtime.SaveDialogOptions{
		DefaultFilename: suggestedName,
		Filters: []runtime.FileFilter{
			{DisplayName: "HIL Run (*.hilbin)", Pattern: "*.hilbin"},
		},
	})
	if err != nil || path == "" {
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
