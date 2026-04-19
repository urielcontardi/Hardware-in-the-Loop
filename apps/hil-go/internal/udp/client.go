// Package udp sends JSON commands to the hil_controller on the PS.
package udp

import (
	"encoding/json"
	"fmt"
	"net"
	"time"
)

// LocalIP returns the first non-loopback IPv4 address of the machine.
func LocalIP() string {
	ifaces, _ := net.Interfaces()
	for _, i := range ifaces {
		addrs, _ := i.Addrs()
		for _, a := range addrs {
			var ip net.IP
			switch v := a.(type) {
			case *net.IPNet:
				ip = v.IP
			case *net.IPAddr:
				ip = v.IP
			}
			if ip == nil || ip.IsLoopback() {
				continue
			}
			if ip4 := ip.To4(); ip4 != nil {
				return ip4.String()
			}
		}
	}
	return "0.0.0.0"
}

const (
	CmdPort   = 5005
	timeoutMs = 2000
)

// HilStatus is the response from {"cmd":"get"}.
type HilStatus struct {
	SpeedRadS   float32 `json:"speed_rad_s"`
	IalphaA     float32 `json:"ialpha_A"`
	IbetaA      float32 `json:"ibeta_A"`
	FluxAlphaWb float32 `json:"flux_alpha_Wb"`
	FluxBetaWb  float32 `json:"flux_beta_Wb"`
	FreqHz      float32 `json:"freq_hz"`
	VdcV        float32 `json:"vdc_v"`
	Enable      int     `json:"enable"`
}

// SetParams are the fields sent with {"cmd":"set"}.
type SetParams struct {
	FreqHz   float32 `json:"freq_hz"`
	VdcV     float32 `json:"vdc_v"`
	TorqueNm float32 `json:"torque_nm"`
	Enable   int     `json:"enable"`
	Decim    int     `json:"decim"`
	TelemDst string  `json:"telem_dst,omitempty"` // PC IP for telemetry push
}

func sendRecv(ip string, payload []byte) ([]byte, error) {
	raddr, err := net.ResolveUDPAddr("udp4", fmt.Sprintf("%s:%d", ip, CmdPort))
	if err != nil {
		return nil, err
	}
	conn, err := net.DialUDP("udp4", nil, raddr)
	if err != nil {
		return nil, err
	}
	defer conn.Close()

	deadline := time.Now().Add(timeoutMs * time.Millisecond)
	conn.SetDeadline(deadline)

	if _, err := conn.Write(payload); err != nil {
		return nil, fmt.Errorf("send: %w", err)
	}

	buf := make([]byte, 1024)
	n, err := conn.Read(buf)
	if err != nil {
		return nil, fmt.Errorf("recv timeout: %w", err)
	}
	return buf[:n], nil
}

// Set sends a "set" command with the given parameters.
func Set(ip string, p SetParams) error {
	type cmdSet struct {
		Cmd      string  `json:"cmd"`
		FreqHz   float32 `json:"freq_hz"`
		VdcV     float32 `json:"vdc_v"`
		TorqueNm float32 `json:"torque_nm"`
		Enable   int     `json:"enable"`
		Decim    int     `json:"decim"`
		TelemDst string  `json:"telem_dst,omitempty"`
	}
	b, _ := json.Marshal(cmdSet{
		Cmd:      "set",
		FreqHz:   p.FreqHz,
		VdcV:     p.VdcV,
		TorqueNm: p.TorqueNm,
		Enable:   p.Enable,
		Decim:    p.Decim,
		TelemDst: p.TelemDst,
	})
	_, err := sendRecv(ip, b)
	return err
}

// Get queries the current controller state.
func Get(ip string) (*HilStatus, error) {
	resp, err := sendRecv(ip, []byte(`{"cmd":"get"}`))
	if err != nil {
		return nil, err
	}
	var s HilStatus
	if err := json.Unmarshal(resp, &s); err != nil {
		return nil, fmt.Errorf("parse: %w — raw: %s", err, resp)
	}
	return &s, nil
}

// Stop sends a "stop" command.
func Stop(ip string) error {
	_, err := sendRecv(ip, []byte(`{"cmd":"stop"}`))
	return err
}
