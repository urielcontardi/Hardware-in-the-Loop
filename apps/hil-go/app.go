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
func (a *App) SetParams(ip string, freqHz, vdcV, torqueNm float32, enable bool, decim int) error {
	en := 0
	if enable {
		en = 1
	}
	return hilUDP.Set(ip, hilUDP.SetParams{
		FreqHz:   freqHz,
		VdcV:     vdcV,
		TorqueNm: torqueNm,
		Enable:   en,
		Decim:    decim,
		TelemDst: a.localIP,
	})
}

// GetStatus polls the current controller state from the PS board.
func (a *App) GetStatus(ip string) (*hilUDP.HilStatus, error) {
	return hilUDP.Get(ip)
}

// StopController sends a stop command to the PS board.
func (a *App) StopController(ip string) error {
	return hilUDP.Stop(ip)
}

// GetStats returns receiver statistics.
func (a *App) GetStats() map[string]uint64 {
	if a.recv == nil {
		return map[string]uint64{}
	}
	return map[string]uint64{
		"samples_rx": a.recv.Stats.SamplesRx.Load(),
		"packets_rx": a.recv.Stats.PacketsRx.Load(),
		"dropped":    a.recv.Stats.Dropped.Load(),
		"crc_errors": a.recv.Stats.CRCErrors.Load(),
		"seq_missed": a.recv.Stats.SeqMissed.Load(),
		"ring_len":   uint64(a.ring.Len()),
	}
}

// GetLocalIP returns the machine's primary non-loopback IPv4 address.
func (a *App) GetLocalIP() string {
	return a.localIP
}
