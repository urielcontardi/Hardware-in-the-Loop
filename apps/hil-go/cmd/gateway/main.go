package main

import (
	"context"
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/receiver"
	"hil.local/daemon/internal/ring"
	hiludp "hil.local/daemon/internal/udp"
)

//go:embed static/*
var staticFiles embed.FS

const (
	defaultHTTPAddr = "127.0.0.1:5177"
	telemetryPort   = 5006
)

type server struct {
	ring        *ring.Ring
	recv        *receiver.Receiver
	localIP     string
	targetMu    sync.RWMutex
	telemTarget string
}

type setRequest struct {
	IP         string   `json:"ip"`
	FreqHz     *float32 `json:"freq_hz,omitempty"`
	VdcV       *float32 `json:"vdc_v,omitempty"`
	TorqueNm   *float32 `json:"torque_nm,omitempty"`
	BaseFreqHz *float32 `json:"base_freq_hz,omitempty"`
	MaxVPu     *float32 `json:"max_v_pu,omitempty"`
	BoostVPu   *float32 `json:"boost_v_pu,omitempty"`
	Enable     *int     `json:"enable,omitempty"`
	Decim      *int     `json:"decim,omitempty"`
	AttachUDP  bool     `json:"attach_udp,omitempty"`
}

type ipRequest struct {
	IP string `json:"ip"`
}

type discoverRequest struct {
	IP string `json:"ip,omitempty"`
}

func main() {
	addr := strings.TrimSpace(os.Getenv("HIL_HTTP_ADDR"))
	if addr == "" {
		addr = defaultHTTPAddr
	}

	r := ring.New(65536)
	recv := receiver.New(telemetryPort, r)
	if err := recv.Start(); err != nil {
		log.Fatalf("telemetry receiver: %v", err)
	}
	defer recv.Stop()

	s := &server{
		ring:    r,
		recv:    recv,
		localIP: localIP(),
	}

	mux := http.NewServeMux()
	mux.Handle("/", s.staticHandler())
	mux.HandleFunc("/api/local-ip", s.handleLocalIP)
	mux.HandleFunc("/api/discover", s.handleDiscover)
	mux.HandleFunc("/api/status", s.handleStatus)
	mux.HandleFunc("/api/attach", s.handleAttach)
	mux.HandleFunc("/api/detach", s.handleDetach)
	mux.HandleFunc("/api/set", s.handleSet)
	mux.HandleFunc("/api/run", s.handleRun)
	mux.HandleFunc("/api/pause", s.handlePause)
	mux.HandleFunc("/api/stop", s.handleStop)
	mux.HandleFunc("/api/stats", s.handleStats)
	mux.HandleFunc("/events", s.handleEvents)

	log.Printf("HIL gateway listening on http://%s", addr)
	log.Printf("local IP for board telemetry: %s", s.localIP)
	log.Printf("telemetry UDP receiver listening on :%d", telemetryPort)
	go s.telemetryPunchLoop()
	if err := http.ListenAndServe(addr, logRequests(mux)); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}

func localIP() string {
	ifaces, _ := net.Interfaces()
	for _, iface := range ifaces {
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		addrs, _ := iface.Addrs()
		for _, addr := range addrs {
			ipNet, ok := addr.(*net.IPNet)
			if !ok {
				continue
			}
			ip4 := ipNet.IP.To4()
			if ip4 != nil {
				return ip4.String()
			}
		}
	}
	return "0.0.0.0"
}

func logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		next.ServeHTTP(w, r)
	})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, err error) {
	writeJSON(w, status, map[string]string{"error": err.Error()})
}

func decodeJSON[T any](r *http.Request) (T, error) {
	var v T
	defer r.Body.Close()
	if err := json.NewDecoder(r.Body).Decode(&v); err != nil {
		return v, err
	}
	return v, nil
}

func requireIP(ip string) error {
	if strings.TrimSpace(ip) == "" {
		return errors.New("missing board IP")
	}
	return nil
}

func (s *server) handleIndex(w http.ResponseWriter, r *http.Request) {
	http.Redirect(w, r, "/", http.StatusFound)
}

func (s *server) staticHandler() http.Handler {
	sub, err := fs.Sub(staticFiles, "static")
	if err != nil {
		panic(err)
	}
	fileServer := http.FileServer(http.FS(sub))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/api/") || r.URL.Path == "/events" {
			http.NotFound(w, r)
			return
		}
		if r.URL.Path == "/" {
			fileServer.ServeHTTP(w, r)
			return
		}
		path := strings.TrimPrefix(r.URL.Path, "/")
		if _, err := fs.Stat(sub, path); err != nil {
			r2 := r.Clone(r.Context())
			r2.URL.Path = "/"
			fileServer.ServeHTTP(w, r2)
			return
		}
		fileServer.ServeHTTP(w, r)
	})
}

func (s *server) handleLegacyIndex(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	_, _ = w.Write([]byte(indexHTML))
}

func (s *server) handleLocalIP(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"ip": s.localIP})
}

func (s *server) handleDiscover(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}

	var req discoverRequest
	if r.Body != nil {
		_ = json.NewDecoder(r.Body).Decode(&req)
		_ = r.Body.Close()
	}

	resp, err := s.resolveBoard(req.IP)
	if err != nil {
		writeError(w, http.StatusConflict, err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

func discoveryFromStatus(ip string, status *hiludp.HilStatus) hiludp.DiscoveryResponse {
	state := ""
	if status != nil {
		state = status.State
	}
	return hiludp.DiscoveryResponse{
		Type:      "hil_discovery",
		Name:      "ebaz4205",
		IP:        ip,
		CmdPort:   hiludp.CmdPort,
		TelemPort: telemetryPort,
		State:     state,
	}
}

func (s *server) scanForBoard() (*hiludp.DiscoveryResponse, error) {
	ip := net.ParseIP(s.localIP).To4()
	if ip == nil {
		return nil, errors.New("gateway has no local IPv4 address for LAN scan")
	}

	prefix := fmt.Sprintf("%d.%d.%d.", ip[0], ip[1], ip[2])
	ctx, cancel := context.WithTimeout(context.Background(), 900*time.Millisecond)
	defer cancel()

	found := make(chan hiludp.DiscoveryResponse, 1)
	var wg sync.WaitGroup
	sem := make(chan struct{}, 32)

	for host := 1; host <= 254; host++ {
		candidate := fmt.Sprintf("%s%d", prefix, host)
		if candidate == s.localIP {
			continue
		}

		wg.Add(1)
		go func(ip string) {
			defer wg.Done()
			select {
			case sem <- struct{}{}:
				defer func() { <-sem }()
			case <-ctx.Done():
				return
			}

			status, err := hiludp.PingTimeout(ip, 220*time.Millisecond)
			if err != nil {
				return
			}
			select {
			case found <- discoveryFromStatus(ip, status):
				cancel()
			default:
			}
		}(candidate)
	}

	done := make(chan struct{})
	go func() {
		wg.Wait()
		close(done)
	}()

	select {
	case resp := <-found:
		return &resp, nil
	case <-done:
		return nil, errors.New("no HIL controller found on local subnet")
	case <-ctx.Done():
		select {
		case resp := <-found:
			return &resp, nil
		default:
			return nil, errors.New("no HIL controller found on local subnet")
		}
	}
}

func (s *server) resolveBoard(preferred string) (*hiludp.DiscoveryResponse, error) {
	candidates := []string{strings.TrimSpace(preferred), s.telemetryTarget()}
	seen := map[string]bool{}
	for _, ip := range candidates {
		if ip == "" || seen[ip] {
			continue
		}
		seen[ip] = true
		status, err := hiludp.PingTimeout(ip, 450*time.Millisecond)
		if err == nil {
			resp := discoveryFromStatus(ip, status)
			s.setTelemetryTarget(ip)
			return &resp, nil
		}
	}

	if resp, err := s.scanForBoard(); err == nil {
		s.setTelemetryTarget(resp.IP)
		return resp, nil
	}

	resp, err := hiludp.Discover(1200 * time.Millisecond)
	if err != nil {
		return nil, err
	}
	s.setTelemetryTarget(resp.IP)
	return resp, nil
}

func (s *server) resolveIP(preferred string) (string, error) {
	resp, err := s.resolveBoard(preferred)
	if err != nil {
		return "", err
	}
	return resp.IP, nil
}

func stampBoardIP(ip string, status *hiludp.HilStatus) *hiludp.HilStatus {
	if status != nil {
		status.BoardIP = ip
	}
	return status
}

func (s *server) handleStatus(w http.ResponseWriter, r *http.Request) {
	ip, err := s.resolveIP(r.URL.Query().Get("ip"))
	if err != nil {
		writeError(w, http.StatusConflict, err)
		return
	}
	status, err := hiludp.Get(ip)
	if err != nil {
		writeError(w, http.StatusConflict, err)
		return
	}
	writeJSON(w, http.StatusOK, stampBoardIP(ip, status))
}

func (s *server) handleAttach(w http.ResponseWriter, r *http.Request) {
	req, err := decodeJSON[ipRequest](r)
	if err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}
	ip, err := s.resolveIP(req.IP)
	if err != nil {
		writeError(w, http.StatusConflict, err)
		return
	}
	s.setTelemetryTarget(ip)
	s.recv.Punch(ip, telemetryPort)
	status, err := hiludp.Telem(ip, s.localIP)
	if err != nil {
		writeError(w, http.StatusConflict, err)
		return
	}
	s.recv.Punch(ip, telemetryPort)
	writeJSON(w, http.StatusOK, stampBoardIP(ip, status))
}

func (s *server) handleDetach(w http.ResponseWriter, r *http.Request) {
	req, err := decodeJSON[ipRequest](r)
	if err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}
	ip, err := s.resolveIP(req.IP)
	if err != nil {
		writeError(w, http.StatusConflict, err)
		return
	}
	status, err := hiludp.TelemOff(ip)
	if err != nil {
		writeError(w, http.StatusConflict, err)
		return
	}
	s.setTelemetryTarget("")
	s.ring.Clear()
	writeJSON(w, http.StatusOK, stampBoardIP(ip, status))
}

func (s *server) handleSet(w http.ResponseWriter, r *http.Request) {
	req, err := decodeJSON[setRequest](r)
	if err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}
	ip, err := s.resolveIP(req.IP)
	if err != nil {
		writeError(w, http.StatusConflict, err)
		return
	}

	p := hiludp.SetParams{
		FreqHz:     req.FreqHz,
		VdcV:       req.VdcV,
		TorqueNm:   req.TorqueNm,
		BaseFreqHz: req.BaseFreqHz,
		MaxVPu:     req.MaxVPu,
		BoostVPu:   req.BoostVPu,
		Enable:     req.Enable,
		Decim:      req.Decim,
	}
	if req.AttachUDP {
		p.TelemDst = s.localIP
		s.setTelemetryTarget(ip)
		s.recv.Punch(ip, telemetryPort)
	}

	status, err := hiludp.Set(ip, p)
	if err != nil {
		writeError(w, http.StatusConflict, err)
		return
	}
	if req.AttachUDP {
		s.recv.Punch(ip, telemetryPort)
	}
	writeJSON(w, http.StatusOK, stampBoardIP(ip, status))
}

func (s *server) handleRun(w http.ResponseWriter, r *http.Request) {
	s.forwardCommand(w, r, hiludp.Run)
}

func (s *server) handlePause(w http.ResponseWriter, r *http.Request) {
	s.forwardCommand(w, r, hiludp.Pause)
}

func (s *server) handleStop(w http.ResponseWriter, r *http.Request) {
	req, err := decodeJSON[ipRequest](r)
	if err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}
	ip, err := s.resolveIP(req.IP)
	if err != nil {
		writeError(w, http.StatusConflict, err)
		return
	}
	status, err := hiludp.Stop(ip)
	if err != nil {
		writeError(w, http.StatusConflict, err)
		return
	}
	_, _ = hiludp.TelemOff(ip)
	s.setTelemetryTarget("")
	s.ring.Clear()
	writeJSON(w, http.StatusOK, stampBoardIP(ip, status))
}

func (s *server) forwardCommand(w http.ResponseWriter, r *http.Request, fn func(string) (*hiludp.HilStatus, error)) {
	req, err := decodeJSON[ipRequest](r)
	if err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}
	ip, err := s.resolveIP(req.IP)
	if err != nil {
		writeError(w, http.StatusConflict, err)
		return
	}
	status, err := fn(ip)
	if err != nil {
		writeError(w, http.StatusConflict, err)
		return
	}
	writeJSON(w, http.StatusOK, stampBoardIP(ip, status))
}

func (s *server) handleStats(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]uint64{
		"packets_raw": s.recv.Stats.PacketsRaw.Load(),
		"samples_rx":  s.recv.Stats.SamplesRx.Load(),
		"packets_rx":  s.recv.Stats.PacketsRx.Load(),
		"dropped":     s.recv.Stats.Dropped.Load(),
		"crc_errors":  s.recv.Stats.CRCErrors.Load(),
		"invalid":     s.recv.Stats.Invalid.Load(),
		"seq_missed":  s.recv.Stats.SeqMissed.Load(),
		"ring_len":    uint64(s.ring.Len()),
	})
}

func (s *server) setTelemetryTarget(ip string) {
	s.targetMu.Lock()
	s.telemTarget = strings.TrimSpace(ip)
	s.targetMu.Unlock()
}

func (s *server) telemetryTarget() string {
	s.targetMu.RLock()
	defer s.targetMu.RUnlock()
	return s.telemTarget
}

func (s *server) telemetryPunchLoop() {
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()
	for range ticker.C {
		s.targetMu.RLock()
		ip := s.telemTarget
		s.targetMu.RUnlock()
		if ip != "" {
			s.recv.Punch(ip, telemetryPort)
		}
	}
}

func (s *server) handleEvents(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		writeError(w, http.StatusInternalServerError, errors.New("streaming unsupported"))
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")

	ctx := r.Context()
	ticker := time.NewTicker(50 * time.Millisecond)
	defer ticker.Stop()
	scratch := make([]frame.Sample, 512)

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			n := s.ring.PopN(scratch)
			if n == 0 {
				continue
			}
			payload, err := json.Marshal(scratch[:n])
			if err != nil {
				continue
			}
			if _, err := fmt.Fprintf(w, "event: telemetry\ndata: %s\n\n", payload); err != nil {
				return
			}
			flusher.Flush()
		}
	}
}

func shutdownServer(ctx context.Context, srv *http.Server) {
	_ = srv.Shutdown(ctx)
}

const indexHTML = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>HIL Gateway</title>
  <style>
    :root { color-scheme: dark; --bg:#070c16; --panel:#0c1421; --line:#1d3147; --fg:#d6e3f3; --muted:#7e9bb8; --ok:#00d4a8; --warn:#f0a030; --bad:#e83050; --blue:#2196d4; }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--fg); font: 14px/1.4 system-ui, sans-serif; }
    header { height: 58px; display: flex; align-items: center; justify-content: space-between; padding: 0 18px; border-bottom: 1px solid var(--line); background: #091221; }
    main { display: grid; grid-template-columns: 320px 1fr; min-height: calc(100vh - 58px); }
    aside { border-right: 1px solid var(--line); background: var(--panel); padding: 14px; overflow: auto; }
    section { border-bottom: 1px solid var(--line); padding: 0 0 14px; margin-bottom: 14px; }
    h1 { font-size: 16px; margin: 0; letter-spacing: .04em; }
    h2 { font-size: 11px; margin: 0 0 10px; color: var(--muted); letter-spacing: .14em; text-transform: uppercase; }
    label { display: grid; grid-template-columns: 105px 1fr; align-items: center; gap: 8px; margin: 8px 0; color: var(--muted); }
    input { width: 100%; background: #09111c; border: 1px solid var(--line); color: var(--fg); border-radius: 5px; padding: 6px 8px; }
    button { background: #0a1b2e; border: 1px solid var(--blue); color: #79cfff; border-radius: 5px; padding: 7px 10px; cursor: pointer; }
    button:hover { background: #0d2540; }
    button.primary { color: var(--ok); border-color: #007c53; background: #002a1a; }
    button.warn { color: var(--warn); border-color: #6a4a00; background: #2a1d00; }
    button.danger { color: var(--bad); border-color: #700020; background: #2e0010; }
    .row { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
    .row3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
    .badge { font: 700 11px ui-monospace, monospace; padding: 5px 10px; border: 1px solid var(--line); border-radius: 5px; color: var(--muted); }
    .badge.ok { color: var(--ok); border-color: #006038; }
    .badge.bad { color: var(--bad); border-color: #700020; }
    .status { min-height: 42px; color: var(--muted); font-family: ui-monospace, monospace; white-space: pre-wrap; }
    .plot { padding: 18px; display: grid; grid-template-rows: 1fr auto; gap: 12px; }
    canvas { width: 100%; height: 100%; min-height: 420px; background: #050914; border: 1px solid var(--line); border-radius: 6px; }
    .stats { display: grid; grid-template-columns: repeat(6, minmax(100px, 1fr)); gap: 8px; }
    .stat { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 10px; }
    .stat span { display: block; color: var(--muted); font-size: 11px; text-transform: uppercase; }
    .stat strong { font: 700 18px ui-monospace, monospace; }
  </style>
</head>
<body>
  <header>
    <h1>HIL Gateway</h1>
    <div id="state" class="badge">OFFLINE</div>
  </header>
  <main>
    <aside>
      <section>
        <h2>Connection</h2>
        <label>Board IP <input id="ip" value="192.168.15.14"></label>
        <div class="row">
          <button id="discover">Find</button>
          <button id="attach">Connect</button>
        </div>
      </section>
      <section>
        <h2>Parameters</h2>
        <label>Freq Hz <input id="freq" type="number" value="60"></label>
        <label>Vdc V <input id="vdc" type="number" value="311"></label>
        <label>Torque <input id="torque" type="number" value="0" step="0.1"></label>
        <button id="apply">Apply Params</button>
      </section>
      <section>
        <h2>Control</h2>
        <div class="row3">
          <button id="run" class="primary">Run</button>
          <button id="pause" class="warn">Pause</button>
          <button id="stop" class="danger">Stop</button>
        </div>
      </section>
      <section>
        <h2>Status</h2>
        <div id="log" class="status">Ready</div>
      </section>
    </aside>
    <div class="plot">
      <canvas id="canvas"></canvas>
      <div class="stats">
        <div class="stat"><span>Samples</span><strong id="samples">0</strong></div>
        <div class="stat"><span>Packets</span><strong id="packets">0</strong></div>
        <div class="stat"><span>Dropped</span><strong id="dropped">0</strong></div>
        <div class="stat"><span>CRC</span><strong id="crc">0</strong></div>
        <div class="stat"><span>Seq Miss</span><strong id="seq">0</strong></div>
        <div class="stat"><span>Buffer</span><strong id="ring">0</strong></div>
      </div>
    </div>
  </main>
  <script>
    const $ = id => document.getElementById(id);
    const log = msg => { $("log").textContent = msg; };
    const post = async (url, body = {}) => {
      const r = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      const text = await r.text();
      let j = null;
      try { j = text ? JSON.parse(text) : null; } catch {}
      if (!r.ok) throw new Error((j && j.error) || text || r.statusText);
      if (!j) throw new Error("empty response from gateway");
      return j;
    };
    const ipBody = () => ({ ip: $("ip").value.trim() });
    const applyStatus = s => {
      $("state").textContent = (s.state || "unknown").toUpperCase();
      $("state").className = "badge " + (s.state === "running" ? "ok" : "");
      if (s.freq_hz != null) $("freq").value = s.freq_hz;
      if (s.vdc_v != null) $("vdc").value = s.vdc_v;
      if (s.torque_nm != null) $("torque").value = s.torque_nm;
      log("state=" + s.state + " freq=" + s.freq_hz + "Hz vdc=" + s.vdc_v + "V torque=" + s.torque_nm + "Nm");
    };
    $("discover").onclick = async () => {
      try { log("Searching..."); const d = await post("/api/discover", ipBody()); $("ip").value = d.ip; log("Found " + d.name + " at " + d.ip + " " + (d.mac || "")); }
      catch (e) { log(e.message); }
    };
    $("attach").onclick = async () => { try { applyStatus(await post("/api/attach", ipBody())); } catch (e) { log(e.message); } };
    $("apply").onclick = async () => {
      try {
        applyStatus(await post("/api/set", { ip: $("ip").value.trim(), freq_hz: Number($("freq").value), vdc_v: Number($("vdc").value), torque_nm: Number($("torque").value), decim: 0, attach_udp: true }));
      } catch (e) { log(e.message); }
    };
    $("run").onclick = async () => { try { applyStatus(await post("/api/run", ipBody())); } catch (e) { log(e.message); } };
    $("pause").onclick = async () => { try { applyStatus(await post("/api/pause", ipBody())); } catch (e) { log(e.message); } };
    $("stop").onclick = async () => { try { applyStatus(await post("/api/stop", ipBody())); } catch (e) { log(e.message); } };

    const c = $("canvas"), ctx = c.getContext("2d");
    const series = [];
    const max = 1200;
    function resize() { c.width = c.clientWidth * devicePixelRatio; c.height = c.clientHeight * devicePixelRatio; }
    new ResizeObserver(resize).observe(c); resize();
    function draw() {
      ctx.clearRect(0, 0, c.width, c.height);
      ctx.strokeStyle = "#1d3147"; ctx.lineWidth = 1;
      for (let i = 1; i < 5; i++) { const y = c.height * i / 5; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(c.width, y); ctx.stroke(); }
      const keys = [["Ia","#4fc3f7"],["Ib","#ef9a9a"],["Speed","#ffcc80"]];
      const vals = series.flatMap(s => [s.Ia, s.Ib, s.Speed]).filter(Number.isFinite);
      const lim = Math.max(1, ...vals.map(v => Math.abs(v)));
      keys.forEach(([k,color]) => {
        ctx.strokeStyle = color; ctx.beginPath();
        series.forEach((s, i) => {
          const x = i * c.width / Math.max(1, max - 1);
          const y = c.height / 2 - (s[k] / lim) * c.height * 0.42;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();
      });
      requestAnimationFrame(draw);
    }
    draw();
    new EventSource("/events").addEventListener("telemetry", e => {
      const samples = JSON.parse(e.data);
      for (const s of samples) series.push(s);
      if (series.length > max) series.splice(0, series.length - max);
    });
    setInterval(async () => {
      try {
        const s = await (await fetch("/api/stats")).json();
        $("samples").textContent = (s.samples_rx || 0).toLocaleString();
        $("packets").textContent = (s.packets_rx || 0).toLocaleString();
        $("dropped").textContent = s.dropped || 0;
        $("crc").textContent = s.crc_errors || 0;
        $("seq").textContent = s.seq_missed || 0;
        $("ring").textContent = s.ring_len || 0;
      } catch {}
    }, 1000);
  </script>
</body>
</html>`
