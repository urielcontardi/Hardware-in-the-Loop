// Package udp sends JSON commands to the hil_controller on the PS.
package udp

import (
	"encoding/json"
	"fmt"
	"net"
	"strings"
	"syscall"
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
	DiscoveryPort = 5004
	CmdPort       = 5005
	timeoutMs     = 1500

	discoveryMagic = "HIL_DISCOVER_V1"
)

// HilStatus is the response the board returns to every command.
// "Status" is the per-call ack ("ok", "unknown_command", "shutting_down", …).
// "State" is the FSM state ("idle", "running", "paused", "stopped").
type HilStatus struct {
	Status           string  `json:"status"`
	State            string  `json:"state"`
	SpeedRadS        float32 `json:"speed_rad_s"`
	IalphaA          float32 `json:"ialpha_A"`
	IbetaA           float32 `json:"ibeta_A"`
	FluxAlphaWb      float32 `json:"flux_alpha_Wb"`
	FluxBetaWb       float32 `json:"flux_beta_Wb"`
	FreqHz           float32 `json:"freq_hz"`
	FreqActualHz     float32 `json:"freq_actual_hz"`
	VdcV             float32 `json:"vdc_v"`
	TorqueNm         float32 `json:"torque_nm"`
	BaseFreqHz       float32 `json:"base_freq_hz"`
	MaxVPu           float32 `json:"max_v_pu"`
	AccelTimeSec     float32 `json:"accel_time_s"`
	Enable           int     `json:"enable"`
	TelemDst         string  `json:"telem_dst"`
	TelemActive      int     `json:"telem_active"`
	TelemPacketsSent uint32  `json:"telem_packets_sent"`
	TelemSendErrors  uint32  `json:"telem_send_errors"`
	BoardIP          string  `json:"board_ip,omitempty"`
}

// DiscoveryResponse is returned by hil_controller on the discovery port.
type DiscoveryResponse struct {
	Type      string `json:"type"`
	Name      string `json:"name"`
	IP        string `json:"ip"`
	MAC       string `json:"mac"`
	CmdPort   int    `json:"cmd_port"`
	TelemPort int    `json:"telem_port"`
	State     string `json:"state"`
}

// SetParams: fields sent with {"cmd":"set"}. Pointers so we can omit fields
// the user did not touch (and let the board keep the previous value).
type SetParams struct {
	FreqHz       *float32 `json:"freq_hz,omitempty"`
	VdcV         *float32 `json:"vdc_v,omitempty"`
	TorqueNm     *float32 `json:"torque_nm,omitempty"`
	BaseFreqHz   *float32 `json:"base_freq_hz,omitempty"`
	MaxVPu       *float32 `json:"max_v_pu,omitempty"`
	AccelTimeSec *float32 `json:"accel_time_s,omitempty"`
	Enable       *int     `json:"enable,omitempty"`
	Decim        *int     `json:"decim,omitempty"`
	TelemDst     string   `json:"telem_dst,omitempty"`
}

func sendRecv(ip string, payload []byte) (*HilStatus, error) {
	return sendRecvTimeout(ip, payload, timeoutMs*time.Millisecond)
}

func sendRecvTimeout(ip string, payload []byte, timeout time.Duration) (*HilStatus, error) {
	raddr, err := net.ResolveUDPAddr("udp4", fmt.Sprintf("%s:%d", ip, CmdPort))
	if err != nil {
		return nil, err
	}
	conn, err := net.DialUDP("udp4", nil, raddr)
	if err != nil {
		return nil, err
	}
	defer conn.Close()

	conn.SetDeadline(time.Now().Add(timeout))

	if _, err := conn.Write(payload); err != nil {
		return nil, fmt.Errorf("send: %w", err)
	}

	buf := make([]byte, 2048)
	n, err := conn.Read(buf)
	if err != nil {
		return nil, fmt.Errorf("recv: %w", err)
	}

	var s HilStatus
	if err := json.Unmarshal(buf[:n], &s); err != nil {
		return nil, fmt.Errorf("parse: %w — raw: %s", err, buf[:n])
	}
	return &s, nil
}

func broadcastAddrs(port int) []string {
	seen := map[string]bool{}
	add := func(ip string, out *[]string) {
		addr := fmt.Sprintf("%s:%d", ip, port)
		if !seen[addr] {
			seen[addr] = true
			*out = append(*out, addr)
		}
	}

	addrs := make([]string, 0, 4)
	add("255.255.255.255", &addrs)

	ifaces, _ := net.Interfaces()
	for _, iface := range ifaces {
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagBroadcast == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		ifaceAddrs, _ := iface.Addrs()
		for _, a := range ifaceAddrs {
			ipNet, ok := a.(*net.IPNet)
			if !ok {
				continue
			}
			ip4 := ipNet.IP.To4()
			mask := ipNet.Mask
			if ip4 == nil || len(mask) != net.IPv4len {
				continue
			}
			bcast := net.IPv4(
				ip4[0]|^mask[0],
				ip4[1]|^mask[1],
				ip4[2]|^mask[2],
				ip4[3]|^mask[3],
			)
			add(bcast.String(), &addrs)
		}
	}
	return addrs
}

// Discover broadcasts a one-shot discovery packet and returns the first board
// that answers. It is intended for setup only, not for the telemetry hot path.
func Discover(timeout time.Duration) (*DiscoveryResponse, error) {
	laddr := &net.UDPAddr{IP: net.IPv4zero, Port: 0}
	conn, err := net.ListenUDP("udp4", laddr)
	if err != nil {
		return nil, err
	}
	defer conn.Close()

	rawConn, err := conn.SyscallConn()
	if err != nil {
		return nil, err
	}
	var sockErr error
	if err := rawConn.Control(func(fd uintptr) {
		sockErr = syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_BROADCAST, 1)
	}); err != nil {
		return nil, err
	}
	if sockErr != nil {
		return nil, sockErr
	}

	if err := conn.SetDeadline(time.Now().Add(timeout)); err != nil {
		return nil, err
	}

	payload := []byte(discoveryMagic)
	for _, addr := range broadcastAddrs(DiscoveryPort) {
		raddr, err := net.ResolveUDPAddr("udp4", addr)
		if err != nil {
			continue
		}
		_, _ = conn.WriteToUDP(payload, raddr)
	}

	buf := make([]byte, 1024)
	for {
		n, addr, err := conn.ReadFromUDP(buf)
		if err != nil {
			return nil, fmt.Errorf("discover: %w", err)
		}

		var resp DiscoveryResponse
		if err := json.Unmarshal(buf[:n], &resp); err != nil {
			continue
		}
		if resp.Type != "hil_discovery" || resp.CmdPort == 0 {
			continue
		}
		if strings.TrimSpace(resp.IP) == "" {
			resp.IP = addr.IP.String()
		}
		return &resp, nil
	}
}

// Set sends a "set" command. Any field left nil/empty is omitted, so the
// board keeps its previous value.
func Set(ip string, p SetParams) (*HilStatus, error) {
	payload := map[string]any{"cmd": "set"}
	if p.FreqHz != nil {
		payload["freq_hz"] = *p.FreqHz
	}
	if p.VdcV != nil {
		payload["vdc_v"] = *p.VdcV
	}
	if p.TorqueNm != nil {
		payload["torque_nm"] = *p.TorqueNm
	}
	if p.BaseFreqHz != nil {
		payload["base_freq_hz"] = *p.BaseFreqHz
	}
	if p.MaxVPu != nil {
		payload["max_v_pu"] = *p.MaxVPu
	}
	if p.AccelTimeSec != nil {
		payload["accel_time_s"] = *p.AccelTimeSec
	}
	if p.Enable != nil {
		payload["enable"] = *p.Enable
	}
	if p.Decim != nil {
		payload["decim"] = *p.Decim
	}
	if p.TelemDst != "" {
		payload["telem_dst"] = p.TelemDst
	}
	b, _ := json.Marshal(payload)
	return sendRecv(ip, b)
}

// Get queries the current controller state.
func Get(ip string) (*HilStatus, error) {
	return sendRecv(ip, []byte(`{"cmd":"get"}`))
}

// Run enables the motor with current params.
func Run(ip string) (*HilStatus, error) {
	return sendRecv(ip, []byte(`{"cmd":"run"}`))
}

// Pause disables the motor but keeps params.
func Pause(ip string) (*HilStatus, error) {
	return sendRecv(ip, []byte(`{"cmd":"pause"}`))
}

// Stop disables the motor and resets params to safe defaults.
// Daemon stays alive — subsequent commands still work.
func Stop(ip string) (*HilStatus, error) {
	return sendRecv(ip, []byte(`{"cmd":"stop"}`))
}

// ResetSolver pulses the FPGA solver_reset bit, zeroing the integrator
// states (currents, fluxes, speed) without clobbering the V/F params.
// Leaves the motor disabled (board reports PAUSED) so the user can
// inspect the cleared state before the next Run.
func ResetSolver(ip string) (*HilStatus, error) {
	return sendRecv(ip, []byte(`{"cmd":"reset"}`))
}

// Telem (re)configures the telemetry push destination.
func Telem(ip, dst string) (*HilStatus, error) {
	b, _ := json.Marshal(map[string]any{"cmd": "telem", "dst": dst})
	return sendRecv(ip, b)
}

// TelemOff stops the board telemetry push while leaving the command daemon alive.
func TelemOff(ip string) (*HilStatus, error) {
	b, _ := json.Marshal(map[string]any{"cmd": "telem", "dst": ""})
	return sendRecv(ip, b)
}

// Ping is a lightweight health check; returns full status on success.
func Ping(ip string) (*HilStatus, error) {
	return sendRecv(ip, []byte(`{"cmd":"ping"}`))
}

// PingTimeout is a short health check used by LAN scans.
func PingTimeout(ip string, timeout time.Duration) (*HilStatus, error) {
	return sendRecvTimeout(ip, []byte(`{"cmd":"ping"}`), timeout)
}

// Shutdown terminates the daemon process. Rare — used only for full restarts.
func Shutdown(ip string) (*HilStatus, error) {
	return sendRecv(ip, []byte(`{"cmd":"shutdown"}`))
}
