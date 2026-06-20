// Package receiver listens for HIL telemetry UDP bursts and pushes samples
// into the ring buffer.
package receiver

import (
	"fmt"
	"log"
	"net"
	"sync"
	"sync/atomic"

	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/ring"
)

// Stats holds atomic counters readable from any goroutine.
type Stats struct {
	PacketsRaw atomic.Uint64
	SamplesRx  atomic.Uint64
	Dropped    atomic.Uint64 // ring full
	CRCErrors  atomic.Uint64
	Invalid    atomic.Uint64
	SeqMissed  atomic.Uint64 // gaps in sequence numbers
	PacketsRx  atomic.Uint64
}

// Receiver is a UDP listener that decodes HIL frames into the ring buffer.
type Receiver struct {
	port  int
	ring  *ring.Ring
	Stats Stats

	conn      *net.UDPConn
	quit      chan struct{}
	handlerMu sync.RWMutex
	onSamples func([]frame.Sample)
}

// New creates a Receiver on the given UDP port.
func New(port int, r *ring.Ring) *Receiver {
	return &Receiver{port: port, ring: r, quit: make(chan struct{})}
}

// SetSampleHandler installs a fast side-channel consumer such as the raw recorder.
func (rv *Receiver) SetSampleHandler(fn func([]frame.Sample)) {
	rv.handlerMu.Lock()
	rv.onSamples = fn
	rv.handlerMu.Unlock()
}

// Start begins listening in a background goroutine.
func (rv *Receiver) Start() error {
	addr, err := net.ResolveUDPAddr("udp4", fmt.Sprintf(":%d", rv.port))
	if err != nil {
		return fmt.Errorf("receiver: resolve: %w", err)
	}
	conn, err := net.ListenUDP("udp4", addr)
	if err != nil {
		return fmt.Errorf("receiver: listen: %w", err)
	}
	rv.conn = conn
	_ = conn.SetReadBuffer(4 << 20)
	go rv.loop()
	return nil
}

// Stop shuts down the receiver.
func (rv *Receiver) Stop() {
	close(rv.quit)
	if rv.conn != nil {
		rv.conn.Close()
	}
}

// Punch sends a tiny packet from the telemetry UDP socket. This keeps stateful
// firewalls/NATs open for the reverse telemetry stream without touching data.
func (rv *Receiver) Punch(ip string, port int) {
	if rv.conn == nil || ip == "" {
		return
	}
	addr, err := net.ResolveUDPAddr("udp4", fmt.Sprintf("%s:%d", ip, port))
	if err != nil {
		return
	}
	_, _ = rv.conn.WriteToUDP([]byte("HIL_TELEM_PUNCH"), addr)
}

func (rv *Receiver) loop() {
	buf := make([]byte, 4096)
	var lastSeq uint32
	first := true

	for {
		select {
		case <-rv.quit:
			return
		default:
		}

		n, _, err := rv.conn.ReadFromUDP(buf)
		if err != nil {
			select {
			case <-rv.quit:
				return
			default:
				continue
			}
		}
		rv.Stats.PacketsRaw.Add(1)

		f, err := frame.Decode(buf[:n])
		if err != nil {
			if err == frame.ErrCRC {
				rv.Stats.CRCErrors.Add(1)
				log.Printf("receiver: CRC error (packet dropped)")
			} else {
				rv.Stats.Invalid.Add(1)
				log.Printf("receiver: invalid telemetry packet: %v", err)
			}
			continue
		}

		// sequence gap detection. A lower sequence number means the board-side
		// telemetry sender restarted; resync without counting a wrap-sized gap.
		if !first && f.Seq > lastSeq {
			gap := f.Seq - lastSeq - 1
			if gap > 0 {
				rv.Stats.SeqMissed.Add(uint64(gap))
				log.Printf("receiver: seq gap %d→%d (%d missed)", lastSeq, f.Seq, gap)
			}
		} else if !first && f.Seq <= lastSeq {
			log.Printf("receiver: sequence restarted %d→%d", lastSeq, f.Seq)
		}
		lastSeq = f.Seq
		first = false

		rv.Stats.PacketsRx.Add(1)
		rv.handlerMu.RLock()
		onSamples := rv.onSamples
		rv.handlerMu.RUnlock()
		if onSamples != nil {
			onSamples(f.Samples)
		}

		for _, s := range f.Samples {
			if !rv.ring.Push(s) {
				rv.Stats.Dropped.Add(1)
			}
		}
		rv.Stats.SamplesRx.Add(uint64(len(f.Samples)))
	}
}
