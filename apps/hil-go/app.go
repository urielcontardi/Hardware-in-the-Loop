package main

import (
	"context"
	"time"

	"github.com/wailsapp/wails/v2/pkg/runtime"

	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/receiver"
	"hil.local/daemon/internal/ring"
	hilUDP "hil.local/daemon/internal/udp"
)

type App struct {
	ctx     context.Context
	recv    *receiver.Receiver
	ring    *ring.Ring
	localIP string
	done    chan struct{}
}

func NewApp() *App {
	return &App{
		ring: ring.New(65536),
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

	go a.broadcastLoop()
	runtime.LogInfof(ctx, "HIL daemon ready — telem destination: %s", a.localIP)
}

func (a *App) shutdown(_ context.Context) {
	close(a.done)
	if a.recv != nil {
		a.recv.Stop()
	}
}

func (a *App) broadcastLoop() {
	ticker := time.NewTicker(16 * time.Millisecond)
	defer ticker.Stop()
	scratch := make([]frame.Sample, 512)

	for {
		select {
		case <-a.done:
			return
		case <-ticker.C:
			n := a.ring.PopN(scratch)
			if n > 0 {
				runtime.EventsEmit(a.ctx, "telemetry", scratch[:n])
			}
		}
	}
}

// SetParams sends control parameters to the PS board.
// Empty/zero "do not change" semantics are encoded via the includeXxx flags
// so the user can update just a subset of params.
func (a *App) SetParams(
	ip string,
	freqHz, vdcV, torqueNm float32,
	baseFreqHz, maxVPu, boostVPu float32,
	enable bool, applyEnable bool,
	decim int,
	attachTelem bool,
) (*hilUDP.HilStatus, error) {
	p := hilUDP.SetParams{
		FreqHz:     &freqHz,
		VdcV:       &vdcV,
		TorqueNm:   &torqueNm,
		BaseFreqHz: &baseFreqHz,
		MaxVPu:     &maxVPu,
		BoostVPu:   &boostVPu,
		Decim:      &decim,
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

// AttachTelemetry tells the board to push telemetry to this PC.
func (a *App) AttachTelemetry(ip string) (*hilUDP.HilStatus, error) {
	return hilUDP.Telem(ip, a.localIP)
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
	}
}

// GetLocalIP returns the machine's primary non-loopback IPv4 address.
func (a *App) GetLocalIP() string {
	return a.localIP
}
