// Package frame decodes the HIL binary telemetry protocol.
//
// Frame layout (all LE):
//
//	[0..3]  SYNC  0x48 0x49 0x4C 0x5A  ("HILZ")
//	[4..7]  SEQ   uint32
//	[8]     FLAGS uint8  (bit0=enable, bit1=fault)
//	[9]     N     uint8  (samples in burst)
//	[10 .. 10+N*26-1]  samples: t_cycles(uint32), epoch(uint16), ia ib flux_a flux_b speed (float32 LE each)
//	[last-1..last]     CRC16/CCITT-FALSE LE
package frame

import (
	"encoding/binary"
	"errors"
	"math"
)

const (
	Sync0 = 0x48
	Sync1 = 0x49
	Sync2 = 0x4C
	Sync3 = 0x5A

	HeaderSize  = 10 // SYNC(4)+SEQ(4)+FLAGS(1)+N(1)
	SampleBytes = 26 // uint32 timestamp + uint16 epoch + 5 × float32
	MaxBurst    = 32
)

var (
	ErrInvalidSync = errors.New("invalid sync")
	ErrCRC         = errors.New("CRC mismatch")
	ErrTruncated   = errors.New("frame truncated")
)

// Sample holds one telemetry point from the PS.
type Sample struct {
	TCycles uint32  `json:"t_cycles"`
	Epoch   uint16  `json:"epoch"`
	Ia      float32 `json:"Ia"`
	Ib      float32 `json:"Ib"`
	FluxA   float32 `json:"FluxA"`
	FluxB   float32 `json:"FluxB"`
	Speed   float32 `json:"Speed"`
}

// Frame is one decoded burst packet.
type Frame struct {
	Seq     uint32
	Flags   uint8
	Samples []Sample
}

// CRC16 computes CRC-16/CCITT-FALSE (poly=0x1021, init=0xFFFF).
func CRC16(data []byte) uint16 {
	crc := uint16(0xFFFF)
	for _, b := range data {
		crc ^= uint16(b) << 8
		for range 8 {
			if crc&0x8000 != 0 {
				crc = (crc << 1) ^ 0x1021
			} else {
				crc <<= 1
			}
		}
	}
	return crc
}

// Decode validates and parses a raw UDP payload.
func Decode(buf []byte) (*Frame, error) {
	if len(buf) < HeaderSize+SampleBytes+2 {
		return nil, ErrTruncated
	}
	if buf[0] != Sync0 || buf[1] != Sync1 || buf[2] != Sync2 || buf[3] != Sync3 {
		return nil, ErrInvalidSync
	}

	seq := binary.LittleEndian.Uint32(buf[4:8])
	flags := buf[8]
	n := int(buf[9])

	need := HeaderSize + n*SampleBytes + 2
	if len(buf) < need {
		return nil, ErrTruncated
	}

	// CRC covers everything before the CRC field
	payload := buf[:HeaderSize+n*SampleBytes]
	gotCRC := binary.LittleEndian.Uint16(buf[HeaderSize+n*SampleBytes:])
	if CRC16(payload) != gotCRC {
		return nil, ErrCRC
	}

	samples := make([]Sample, n)
	pos := HeaderSize
	for i := range samples {
		tCycles := binary.LittleEndian.Uint32(buf[pos:])
		epoch := binary.LittleEndian.Uint16(buf[pos+4:])
		fpos := pos + 6
		samples[i] = Sample{
			TCycles: tCycles,
			Epoch:   epoch,
			Ia:      math.Float32frombits(binary.LittleEndian.Uint32(buf[fpos:])),
			Ib:      math.Float32frombits(binary.LittleEndian.Uint32(buf[fpos+4:])),
			FluxA:   math.Float32frombits(binary.LittleEndian.Uint32(buf[fpos+8:])),
			FluxB:   math.Float32frombits(binary.LittleEndian.Uint32(buf[fpos+12:])),
			Speed:   math.Float32frombits(binary.LittleEndian.Uint32(buf[fpos+16:])),
		}
		pos += SampleBytes
	}

	return &Frame{Seq: seq, Flags: flags, Samples: samples}, nil
}
