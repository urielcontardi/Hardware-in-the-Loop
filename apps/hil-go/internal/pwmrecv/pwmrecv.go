package pwmrecv

import (
	"encoding/json"
	"fmt"
	"net"
	"sync/atomic"
)

type Event struct {
	TCycles uint32 `json:"t_cycles"`
	A       uint8  `json:"a"`
	B       uint8  `json:"b"`
	C       uint8  `json:"c"`
	Mask    uint8  `json:"mask"`
	Epoch   uint16 `json:"epoch"`
}

type Batch struct {
	Type    string  `json:"type"`
	Seq     uint32  `json:"seq"`
	ClockHz uint32  `json:"clock_hz"`
	Status  uint32  `json:"status"`
	Events  []Event `json:"events"`
}

type rawBatch struct {
	Type    string      `json:"type"`
	Seq     uint32      `json:"seq"`
	ClockHz uint32      `json:"clock_hz"`
	Status  uint32      `json:"status"`
	Events  [][6]uint32 `json:"events"`
}

type Stats struct {
	PacketsRx atomic.Uint64
	Invalid   atomic.Uint64
	Dropped   atomic.Uint64
	EventsRx  atomic.Uint64
}

type Receiver struct {
	port  int
	C     chan Batch
	Stats Stats

	conn *net.UDPConn
	quit chan struct{}
}

func New(port int) *Receiver {
	return &Receiver{port: port, C: make(chan Batch, 128), quit: make(chan struct{})}
}

func (r *Receiver) Start() error {
	addr, err := net.ResolveUDPAddr("udp4", fmt.Sprintf(":%d", r.port))
	if err != nil {
		return err
	}
	conn, err := net.ListenUDP("udp4", addr)
	if err != nil {
		return err
	}
	r.conn = conn
	go r.loop()
	return nil
}

func (r *Receiver) Stop() {
	close(r.quit)
	if r.conn != nil {
		_ = r.conn.Close()
	}
}

func (r *Receiver) Punch(ip string, port int) {
	if r.conn == nil || ip == "" {
		return
	}
	addr, err := net.ResolveUDPAddr("udp4", fmt.Sprintf("%s:%d", ip, port))
	if err != nil {
		return
	}
	_, _ = r.conn.WriteToUDP([]byte("HIL_PWM_PUNCH"), addr)
}

func (r *Receiver) loop() {
	buf := make([]byte, 16384)
	for {
		select {
		case <-r.quit:
			return
		default:
		}
		n, _, err := r.conn.ReadFromUDP(buf)
		if err != nil {
			select {
			case <-r.quit:
				return
			default:
				continue
			}
		}
		var raw rawBatch
		if err := json.Unmarshal(buf[:n], &raw); err != nil || raw.Type != "pwm_events" {
			r.Stats.Invalid.Add(1)
			continue
		}
		b := Batch{Type: raw.Type, Seq: raw.Seq, ClockHz: raw.ClockHz, Status: raw.Status, Events: make([]Event, 0, len(raw.Events))}
		for _, e := range raw.Events {
			b.Events = append(b.Events, Event{TCycles: e[0], A: uint8(e[1]), B: uint8(e[2]), C: uint8(e[3]), Mask: uint8(e[4]), Epoch: uint16(e[5])})
		}
		r.Stats.PacketsRx.Add(1)
		r.Stats.EventsRx.Add(uint64(len(b.Events)))
		select {
		case r.C <- b:
		default:
			r.Stats.Dropped.Add(1)
		}
	}
}
