// Package receiver listens for HIL telemetry UDP bursts and pushes samples
// into the ring buffer.
package receiver

import (
	"fmt"
	"log"
	"net"
	"sync/atomic"

	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/ring"
)

// Stats holds atomic counters readable from any goroutine.
type Stats struct {
	SamplesRx  atomic.Uint64
	Dropped    atomic.Uint64 // ring full
	CRCErrors  atomic.Uint64
	SeqMissed  atomic.Uint64 // gaps in sequence numbers
	PacketsRx  atomic.Uint64
}

// Receiver is a UDP listener that decodes HIL frames into the ring buffer.
type Receiver struct {
	port  int
	ring  *ring.Ring
	Stats Stats

	conn *net.UDPConn
	quit chan struct{}
}

// New creates a Receiver on the given UDP port.
func New(port int, r *ring.Ring) *Receiver {
	return &Receiver{port: port, ring: r, quit: make(chan struct{})}
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

		f, err := frame.Decode(buf[:n])
		if err != nil {
			if err == frame.ErrCRC {
				rv.Stats.CRCErrors.Add(1)
				log.Printf("receiver: CRC error (packet dropped)")
			}
			continue
		}

		// sequence gap detection
		if !first {
			gap := f.Seq - lastSeq - 1
			if gap > 0 {
				rv.Stats.SeqMissed.Add(uint64(gap))
				log.Printf("receiver: seq gap %d→%d (%d missed)", lastSeq, f.Seq, gap)
			}
		}
		lastSeq = f.Seq
		first = false

		rv.Stats.PacketsRx.Add(1)

		for _, s := range f.Samples {
			if !rv.ring.Push(s) {
				rv.Stats.Dropped.Add(1)
			}
		}
		rv.Stats.SamplesRx.Add(uint64(len(f.Samples)))
	}
}
