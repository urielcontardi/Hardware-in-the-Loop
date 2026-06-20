# Navegação fluida por pirâmide LOD (Plano 1: pipeline ao vivo) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir o pipeline de visualização por uma pirâmide multi-resolução no backend servida por tiles cacheáveis, com um caminho de render único no front, eliminando lag, costura e flicker no zoom/pan da sessão ao vivo.

**Architecture:** O pacote `internal/overview` evolui para `internal/pyramid`, que mantém tiers de buckets min/max/mean (T1 1ms, T2 20ms, T3 500ms, T4 10s) alimentados na ingestão. Dois handlers HTTP (`/api/tiers`, `/api/tiles`) expõem metadados e blocos de buckets imutáveis. No front, um `TileCache` mais um `ViewportController` reescrito escolhem o tier pelo zoom, buscam só os tiles ausentes e alimentam um render único (banda min/max + mean). T0 (raw) continua no `/api/raw`.

**Tech Stack:** Go (gateway), TypeScript + uPlot + Vitest (frontend), testes `go test`.

**Escopo:** Apenas a sessão ao vivo. Visualizar runs salvos (`.hilbin`) e `pyramid.BuildFromStore` ficam para o Plano 2. `handleSeries` é aposentado neste plano.

**Diretório de trabalho:** `apps/hil-go` (rode os comandos Go a partir daí; os comandos npm a partir de `apps/hil-go/frontend`).

---

## File Structure

- Create: `apps/hil-go/internal/pyramid/pyramid.go` — tiers, Push, SelectTier, Tile, Reset.
- Create: `apps/hil-go/internal/pyramid/pyramid_test.go` — testes do pacote.
- Create: `apps/hil-go/internal/pyramid/encode.go` — formato wire do tile.
- Create: `apps/hil-go/internal/pyramid/encode_test.go` — golden bytes.
- Modify: `apps/hil-go/cmd/gateway/main.go` — troca overview por pyramid, handlers `/api/tiers` e `/api/tiles`, aposenta `handleSeries`.
- Create: `apps/hil-go/cmd/gateway/tiles_test.go` — testes dos handlers.
- Create: `apps/hil-go/frontend/src/tile.ts` — tipos e decode do tile.
- Create: `apps/hil-go/frontend/src/tile.test.ts`
- Create: `apps/hil-go/frontend/src/tilecache.ts` — cache LRU de tiles + montagem da janela.
- Create: `apps/hil-go/frontend/src/tilecache.test.ts`
- Modify: `apps/hil-go/frontend/src/viewport.ts` — seleção de tier + descarte de resposta obsoleta.
- Create: `apps/hil-go/frontend/src/viewport.test.ts` (substitui o existente)
- Modify: `apps/hil-go/frontend/src/main.ts` — caminho de render único, botão "Voltar ao vivo", remoção dos buffers antigos.

---

## Task 1: pacote `pyramid` — tiers, Push, Reset

**Files:**
- Create: `apps/hil-go/internal/pyramid/pyramid.go`
- Test: `apps/hil-go/internal/pyramid/pyramid_test.go`

- [ ] **Step 1: Write the failing test**

```go
package pyramid

import (
	"testing"

	"hil.local/daemon/internal/derive"
)

func ch(v float64) [derive.NumChannels]float64 {
	var a [derive.NumChannels]float64
	a[0] = v
	return a
}

func TestPushFoldsMinMaxMeanPerTier(t *testing.T) {
	p := New(10000) // 10 kHz
	// Three samples inside the same T1 (1 ms) bucket: t in [0, 0.001).
	p.Push(0.0000, ch(1))
	p.Push(0.0003, ch(5))
	p.Push(0.0006, ch(-3))
	// One sample in the next T1 bucket.
	p.Push(0.0012, ch(2))

	t1 := p.Tier(0) // T1 = 1 ms
	got := t1.Buckets()
	if len(got) != 2 {
		t.Fatalf("T1 buckets = %d, want 2", len(got))
	}
	if got[0].Min[0] != -3 || got[0].Max[0] != 5 {
		t.Errorf("bucket0 min/max = %v/%v, want -3/5", got[0].Min[0], got[0].Max[0])
	}
	if got[0].Count != 3 || got[0].Mean[0] != 1 { // (1+5-3)/3 = 1
		t.Errorf("bucket0 count/mean = %d/%v, want 3/1", got[0].Count, got[0].Mean[0])
	}
	if got[1].Min[0] != 2 || got[1].Max[0] != 2 {
		t.Errorf("bucket1 min/max = %v/%v, want 2/2", got[1].Min[0], got[1].Max[0])
	}
}

func TestResetClearsAllTiers(t *testing.T) {
	p := New(10000)
	p.Push(0.0, ch(1))
	p.Reset()
	if len(p.Tier(0).Buckets()) != 0 {
		t.Fatalf("after Reset T1 not empty")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/pyramid/`
Expected: FAIL (package/functions not defined).

- [ ] **Step 3: Write minimal implementation**

```go
// Package pyramid keeps a multi-resolution min/max/mean envelope of every
// display channel across several fixed bucket widths (tiers). It backs the
// tile API so any zoom level renders in O(pixels) instead of O(samples). The
// raw tier (T0) lives in rawbuf/store, not here; pyramid covers T1..T4.
package pyramid

import (
	"sync"

	"hil.local/daemon/internal/derive"
)

// BucketsPerTile is the fixed number of buckets per cacheable tile.
const BucketsPerTile = 1024

// defaultBucketSecs are the tier widths in seconds (ascending).
var defaultBucketSecs = []float64{0.001, 0.020, 0.500, 10.0}

// Bucket is the min/max/mean envelope of one time bucket for all channels.
type Bucket struct {
	TStart float64
	Min    [derive.NumChannels]float64
	Max    [derive.NumChannels]float64
	Mean   [derive.NumChannels]float64
	Count  int
}

type tier struct {
	bucketSec float64
	cols      []Bucket
	curIndex  int64
	have      bool
}

// Buckets returns the tier's buckets in time order (read-only use).
func (t *tier) Buckets() []Bucket { return t.cols }

// BucketSec reports the tier resolution in seconds.
func (t *tier) BucketSec() float64 { return t.bucketSec }

func (t *tier) push(ts float64, v [derive.NumChannels]float64) {
	idx := int64(ts / t.bucketSec)
	if !t.have || idx != t.curIndex {
		t.cols = append(t.cols, Bucket{
			TStart: float64(idx) * t.bucketSec,
			Min:    v, Max: v, Mean: v, Count: 1,
		})
		t.curIndex = idx
		t.have = true
		return
	}
	b := &t.cols[len(t.cols)-1]
	b.Count++
	n := float64(b.Count)
	for i := 0; i < derive.NumChannels; i++ {
		if v[i] < b.Min[i] {
			b.Min[i] = v[i]
		}
		if v[i] > b.Max[i] {
			b.Max[i] = v[i]
		}
		b.Mean[i] += (v[i] - b.Mean[i]) / n // running mean
	}
}

// Pyramid is the concurrency-safe set of tiers.
type Pyramid struct {
	mu    sync.RWMutex
	tiers []*tier
	rateH float64
}

// New builds a pyramid for the given telemetry sample rate (Hz).
func New(sampleRateHz float64) *Pyramid {
	if sampleRateHz <= 0 {
		sampleRateHz = 10000
	}
	ts := make([]*tier, len(defaultBucketSecs))
	for i, bs := range defaultBucketSecs {
		ts[i] = &tier{bucketSec: bs, curIndex: -1}
	}
	return &Pyramid{tiers: ts, rateH: sampleRateHz}
}

// Push folds one derived-channel sample into every tier independently. Folding
// from raw into each tier (rather than cascading) keeps min/max/mean exact.
func (p *Pyramid) Push(t float64, v [derive.NumChannels]float64) {
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, tr := range p.tiers {
		tr.push(t, v)
	}
}

// NumTiers reports how many tiers exist (T1..Tn).
func (p *Pyramid) NumTiers() int { return len(p.tiers) }

// Tier returns tier i (0 == finest, T1).
func (p *Pyramid) Tier(i int) *tier { return p.tiers[i] }

// SampleRateHz reports the configured rate.
func (p *Pyramid) SampleRateHz() float64 { return p.rateH }

// Reset clears every tier (call on new run/epoch/motor change).
func (p *Pyramid) Reset() {
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, tr := range p.tiers {
		tr.cols, tr.curIndex, tr.have = nil, -1, false
	}
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/pyramid/`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/internal/pyramid/pyramid.go apps/hil-go/internal/pyramid/pyramid_test.go
git commit -m "feat(pyramid): tiers com Push/Reset min/max/mean por canal derivado"
```

---

## Task 2: pacote `pyramid` — SelectTier e Tile/sealed

**Files:**
- Modify: `apps/hil-go/internal/pyramid/pyramid.go`
- Test: `apps/hil-go/internal/pyramid/pyramid_test.go`

- [ ] **Step 1: Write the failing test**

```go
func TestSelectTierByZoom(t *testing.T) {
	p := New(10000)
	// bucketSec tiers: 0.001, 0.020, 0.500, 10.0
	if got := p.SelectTier(0.0001); got != -1 { // muito zoom: usa raw
		t.Errorf("SelectTier(0.0001)=%d, want -1", got)
	}
	if got := p.SelectTier(0.002); got != 0 { // 1ms cabe
		t.Errorf("SelectTier(0.002)=%d, want 0", got)
	}
	if got := p.SelectTier(0.6); got != 2 { // 500ms cabe, 10s nao
		t.Errorf("SelectTier(0.6)=%d, want 2", got)
	}
	if got := p.SelectTier(100); got != 3 { // coarsest
		t.Errorf("SelectTier(100)=%d, want 3", got)
	}
}

func TestTileWindowingAndSealed(t *testing.T) {
	p := New(10000)
	// T1 (1ms). Tile 0 covers buckets [0,1024) -> t in [0, 1.024).
	// Push samples up to t=1.5s so tile 0 is fully in the past (sealed).
	for i := 0; i < 1600; i++ {
		p.Push(float64(i)*0.001, ch(float64(i)))
	}
	buckets, sealed := p.Tile(0, 0)
	if !sealed {
		t.Errorf("tile 0 should be sealed once data passed its end")
	}
	if len(buckets) != 1024 {
		t.Fatalf("tile 0 buckets = %d, want 1024", len(buckets))
	}
	if buckets[0].TStart != 0 {
		t.Errorf("tile0 first TStart = %v, want 0", buckets[0].TStart)
	}
	// The trailing tile (index 1) is not sealed yet.
	_, sealed1 := p.Tile(0, 1)
	if sealed1 {
		t.Errorf("trailing tile 1 should not be sealed")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/pyramid/ -run 'SelectTier|Tile'`
Expected: FAIL (methods not defined).

- [ ] **Step 3: Write minimal implementation**

Adicione ao final de `apps/hil-go/internal/pyramid/pyramid.go`:

```go
import "sort" // junte aos imports existentes no topo do arquivo

// SelectTier returns the coarsest tier whose bucket is <= secPerPx (so it still
// yields at least one bucket per pixel). Returns -1 when even the finest tier is
// coarser than the zoom, meaning the caller should fall back to raw (T0).
func (p *Pyramid) SelectTier(secPerPx float64) int {
	best := -1
	for i, tr := range p.tiers {
		if tr.bucketSec <= secPerPx {
			best = i
		}
	}
	return best
}

// Tile returns the buckets of tile `index` on `tier` (1024 buckets per tile,
// fixed time boundaries) and whether the tile is sealed (immutable: newer data
// already exists past the tile's end, so it will never change again).
func (p *Pyramid) Tile(tier, index int) ([]Bucket, bool) {
	p.mu.RLock()
	defer p.mu.RUnlock()
	if tier < 0 || tier >= len(p.tiers) || index < 0 {
		return nil, false
	}
	tr := p.tiers[tier]
	startT := float64(int64(index)*BucketsPerTile) * tr.bucketSec
	endT := float64(int64(index+1)*BucketsPerTile) * tr.bucketSec
	lo := sort.Search(len(tr.cols), func(i int) bool { return tr.cols[i].TStart >= startT })
	hi := sort.Search(len(tr.cols), func(i int) bool { return tr.cols[i].TStart >= endT })
	out := make([]Bucket, hi-lo)
	copy(out, tr.cols[lo:hi])
	sealed := tr.have && tr.cols[len(tr.cols)-1].TStart >= endT
	return out, sealed
}

// TileStartSec returns the nominal start time of tile `index` on `tier`.
func (p *Pyramid) TileStartSec(tier, index int) float64 {
	if tier < 0 || tier >= len(p.tiers) {
		return 0
	}
	return float64(int64(index)*BucketsPerTile) * p.tiers[tier].bucketSec
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/pyramid/`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/internal/pyramid/pyramid.go apps/hil-go/internal/pyramid/pyramid_test.go
git commit -m "feat(pyramid): SelectTier por zoom e Tile com flag sealed"
```

---

## Task 3: pacote `pyramid` — formato wire do tile

**Files:**
- Create: `apps/hil-go/internal/pyramid/encode.go`
- Test: `apps/hil-go/internal/pyramid/encode_test.go`

- [ ] **Step 1: Write the failing test**

```go
package pyramid

import (
	"encoding/binary"
	"math"
	"testing"

	"hil.local/daemon/internal/derive"
)

func TestEncodeTileRoundtripHeader(t *testing.T) {
	bs := []Bucket{
		{TStart: 0.0, Min: ch(-3), Max: ch(5), Mean: ch(1), Count: 3},
		{TStart: 0.001, Min: ch(2), Max: ch(2), Mean: ch(2), Count: 1},
	}
	b := EncodeTile(0, 0.001, 0.0, bs)

	if got := b[0]; got != 0 {
		t.Errorf("tier byte = %d, want 0", got)
	}
	if got := binary.LittleEndian.Uint16(b[1:3]); got != 2 {
		t.Errorf("count = %d, want 2", got)
	}
	if got := b[3]; got != derive.NumChannels {
		t.Errorf("nch = %d, want %d", got, derive.NumChannels)
	}
	if got := math.Float32frombits(binary.LittleEndian.Uint32(b[4:8])); got != 0.001 {
		t.Errorf("bucketSec = %v, want 0.001", got)
	}
	// First bucket: tStart at offset 13, then channel 0 min at 17.
	const hdr = 13
	if got := math.Float32frombits(binary.LittleEndian.Uint32(b[hdr:hdr+4])); got != 0 {
		t.Errorf("bucket0 tStart = %v, want 0", got)
	}
	min0 := math.Float32frombits(binary.LittleEndian.Uint32(b[hdr+4 : hdr+8]))
	max0 := math.Float32frombits(binary.LittleEndian.Uint32(b[hdr+8 : hdr+12]))
	if min0 != -3 || max0 != 5 {
		t.Errorf("bucket0 ch0 min/max = %v/%v, want -3/5", min0, max0)
	}
}

func TestEncodeTileLength(t *testing.T) {
	bs := []Bucket{{TStart: 0}}
	b := EncodeTile(1, 0.02, 0, bs)
	want := 13 + 1*(4+derive.NumChannels*12)
	if len(b) != want {
		t.Fatalf("len = %d, want %d", len(b), want)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/pyramid/ -run Encode`
Expected: FAIL (EncodeTile not defined).

- [ ] **Step 3: Write minimal implementation**

```go
package pyramid

import (
	"encoding/binary"
	"math"

	"hil.local/daemon/internal/derive"
)

// EncodeTile serializes a tile to the compact binary the front end parses.
// Wire format (LE):
//   header: tier u8, bucketsCount u16, nch u8, bucketSec f32, tStart0 f32
//   per bucket: tStart f32, then nch×(min f32, max f32, mean f32)
func EncodeTile(tier int, bucketSec, tStart0 float64, buckets []Bucket) []byte {
	const headerBytes = 13 // 1+2+1+4+4
	const perCh = 12       // min,max,mean
	recSize := 4 + derive.NumChannels*perCh
	b := make([]byte, headerBytes+len(buckets)*recSize)
	b[0] = byte(tier)
	binary.LittleEndian.PutUint16(b[1:3], uint16(len(buckets)))
	b[3] = derive.NumChannels
	binary.LittleEndian.PutUint32(b[4:8], math.Float32bits(float32(bucketSec)))
	binary.LittleEndian.PutUint32(b[8:12], math.Float32bits(float32(tStart0)))
	// b[12] reserved/padding so the header is 13 bytes and bucket records align
	// to a clean offset; kept zero.
	off := headerBytes
	for _, bk := range buckets {
		binary.LittleEndian.PutUint32(b[off:], math.Float32bits(float32(bk.TStart)))
		off += 4
		for ch := 0; ch < derive.NumChannels; ch++ {
			binary.LittleEndian.PutUint32(b[off:], math.Float32bits(float32(bk.Min[ch])))
			binary.LittleEndian.PutUint32(b[off+4:], math.Float32bits(float32(bk.Max[ch])))
			binary.LittleEndian.PutUint32(b[off+8:], math.Float32bits(float32(bk.Mean[ch])))
			off += perCh
		}
	}
	return b
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/pyramid/`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/internal/pyramid/encode.go apps/hil-go/internal/pyramid/encode_test.go
git commit -m "feat(pyramid): formato wire EncodeTile"
```

---

## Task 4: gateway — trocar overview por pyramid na ingestão

**Files:**
- Modify: `apps/hil-go/cmd/gateway/main.go` (campo do server, New, ingestão, resetSessionLocked)

- [ ] **Step 1: Trocar o import e o campo do server**

Em `apps/hil-go/cmd/gateway/main.go`, no bloco de imports, substitua a linha do overview:

```go
	"hil.local/daemon/internal/pyramid"
```

(remova o import `"hil.local/daemon/internal/overview"`.)

Na struct `server` (perto da linha 82), troque:

```go
	overview *overview.Overview
```
por:
```go
	pyramid  *pyramid.Pyramid
```

- [ ] **Step 2: Atualizar a construção em main()**

Perto da linha 161, troque:
```go
	ov := overview.New(0.050)
```
por:
```go
	pyr := pyramid.New(gpioFallbackHz)
```

No literal `s := &server{...}` (perto da linha 200), troque:
```go
		overview:  ov,
```
por:
```go
		pyramid:   pyr,
```

- [ ] **Step 3: Atualizar o handler de ingestão**

Na closure `SetSampleHandler` (linha ~185), troque:
```go
			cur.overview.Push(t, m.Compute(smp).Values())
```
por:
```go
			cur.pyramid.Push(t, m.Compute(smp).Values())
```

- [ ] **Step 4: Atualizar resetSessionLocked**

Na função `resetSessionLocked` (perto da linha 830), troque:
```go
	s.overview.Reset()
```
por:
```go
	s.pyramid.Reset()
```

- [ ] **Step 5: Compilar (vai falhar em handleSeries por enquanto, e tudo bem se referenciar overview ali; senão segue)**

Run: `go build ./...`
Expected: PASS (nenhuma referência restante a `overview`). Se o build acusar `overview` não usado em algum ponto, remova essa referência (será o `handleSeries`, aposentado na Task 8).

- [ ] **Step 6: Rodar os testes do gateway que já existem**

Run: `go test ./cmd/gateway/`
Expected: PASS (ou apenas falhas em `series_handler_test.go`, tratadas na Task 8).

- [ ] **Step 7: Commit**

```bash
git add apps/hil-go/cmd/gateway/main.go
git commit -m "refactor(gateway): ingestao alimenta pyramid no lugar de overview"
```

---

## Task 5: gateway — handler `/api/tiers`

**Files:**
- Modify: `apps/hil-go/cmd/gateway/main.go` (novo handler + rota)
- Test: `apps/hil-go/cmd/gateway/tiles_test.go`

- [ ] **Step 1: Write the failing test**

```go
package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"hil.local/daemon/internal/derive"
	"hil.local/daemon/internal/pyramid"
)

func newTestServer() *server {
	return &server{
		pyramid: pyramid.New(10000),
		motor:   derive.DefaultMotor,
	}
}

func TestHandleTiersJSON(t *testing.T) {
	s := newTestServer()
	var v [derive.NumChannels]float64
	v[0] = 1
	s.pyramid.Push(0.0, v)
	s.pyramid.Push(0.5, v)

	req := httptest.NewRequest(http.MethodGet, "/api/tiers", nil)
	rec := httptest.NewRecorder()
	s.handleTiers(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var meta tiersMeta
	if err := json.Unmarshal(rec.Body.Bytes(), &meta); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if meta.SampleRateHz != 10000 {
		t.Errorf("sampleRate = %v, want 10000", meta.SampleRateHz)
	}
	if len(meta.Tiers) != 4 {
		t.Fatalf("tiers = %d, want 4", len(meta.Tiers))
	}
	if meta.Tiers[0].BucketSec != 0.001 {
		t.Errorf("tier0 bucketSec = %v, want 0.001", meta.Tiers[0].BucketSec)
	}
	if meta.TLast < 0.5 {
		t.Errorf("tLast = %v, want >= 0.5", meta.TLast)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./cmd/gateway/ -run HandleTiers`
Expected: FAIL (handleTiers/tiersMeta not defined).

- [ ] **Step 3: Write minimal implementation**

Adicione em `apps/hil-go/cmd/gateway/main.go`:

```go
type tierMeta struct {
	Tier      int     `json:"tier"`
	BucketSec float64 `json:"bucketSec"`
}

type tiersMeta struct {
	SampleRateHz   float64    `json:"sampleRateHz"`
	BucketsPerTile int        `json:"bucketsPerTile"`
	TFirst         float64    `json:"tFirst"`
	TLast          float64    `json:"tLast"`
	Tiers          []tierMeta `json:"tiers"`
}

// handleTiers reports the pyramid layout and current session span so the front
// can pick a tier for a given zoom and compute which tile indices to fetch.
func (s *server) handleTiers(w http.ResponseWriter, r *http.Request) {
	s.ingestMu.Lock()
	p := s.pyramid
	st := s.store
	s.ingestMu.Unlock()

	meta := tiersMeta{
		SampleRateHz:   p.SampleRateHz(),
		BucketsPerTile: pyramid.BucketsPerTile,
	}
	for i := 0; i < p.NumTiers(); i++ {
		meta.Tiers = append(meta.Tiers, tierMeta{Tier: i, BucketSec: p.Tier(i).BucketSec()})
	}
	if st != nil {
		meta.TFirst, meta.TLast = st.Span()
	}
	writeJSON(w, http.StatusOK, meta)
}
```

Registre a rota perto das outras (linha ~222):
```go
	mux.HandleFunc("/api/tiers", s.handleTiers)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./cmd/gateway/ -run HandleTiers`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/cmd/gateway/main.go apps/hil-go/cmd/gateway/tiles_test.go
git commit -m "feat(gateway): handler /api/tiers com layout da piramide"
```

---

## Task 6: gateway — handler `/api/tiles`

**Files:**
- Modify: `apps/hil-go/cmd/gateway/main.go` (handler + rota)
- Test: `apps/hil-go/cmd/gateway/tiles_test.go`

- [ ] **Step 1: Write the failing test**

```go
func TestHandleTilesBytesAndCache(t *testing.T) {
	s := newTestServer()
	var v [derive.NumChannels]float64
	// Fill past tile 0 of T1 so it is sealed.
	for i := 0; i < 1600; i++ {
		v[0] = float64(i)
		s.pyramid.Push(float64(i)*0.001, v)
	}
	req := httptest.NewRequest(http.MethodGet, "/api/tiles?tier=0&index=0", nil)
	rec := httptest.NewRecorder()
	s.handleTiles(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	body := rec.Body.Bytes()
	if body[0] != 0 {
		t.Errorf("tier byte = %d, want 0", body[0])
	}
	if cc := rec.Header().Get("Cache-Control"); cc == "" || cc == "no-store" {
		t.Errorf("sealed tile Cache-Control = %q, want immutable", cc)
	}

	// Trailing tile must be no-store.
	req2 := httptest.NewRequest(http.MethodGet, "/api/tiles?tier=0&index=1", nil)
	rec2 := httptest.NewRecorder()
	s.handleTiles(rec2, req2)
	if cc := rec2.Header().Get("Cache-Control"); cc != "no-store" {
		t.Errorf("trailing tile Cache-Control = %q, want no-store", cc)
	}
}

func TestHandleTilesBadTier(t *testing.T) {
	s := newTestServer()
	req := httptest.NewRequest(http.MethodGet, "/api/tiles?tier=9&index=0", nil)
	rec := httptest.NewRecorder()
	s.handleTiles(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./cmd/gateway/ -run HandleTiles`
Expected: FAIL (handleTiles not defined).

- [ ] **Step 3: Write minimal implementation**

```go
// handleTiles answers GET /api/tiles?tier=T&index=I with one encoded tile.
// Sealed tiles are immutable and cached aggressively; the trailing tile is
// no-store because it is still growing.
func (s *server) handleTiles(w http.ResponseWriter, r *http.Request) {
	tier, errT := strconv.Atoi(r.URL.Query().Get("tier"))
	index, errI := strconv.Atoi(r.URL.Query().Get("index"))
	s.ingestMu.Lock()
	p := s.pyramid
	s.ingestMu.Unlock()
	if errT != nil || errI != nil || tier < 0 || tier >= p.NumTiers() || index < 0 {
		http.Error(w, "bad tier/index", http.StatusBadRequest)
		return
	}
	buckets, sealed := p.Tile(tier, index)
	w.Header().Set("Content-Type", "application/octet-stream")
	if sealed {
		w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
	} else {
		w.Header().Set("Cache-Control", "no-store")
	}
	_, _ = w.Write(pyramid.EncodeTile(tier, p.Tier(tier).BucketSec(), p.TileStartSec(tier, index), buckets))
}
```

Registre a rota (linha ~222):
```go
	mux.HandleFunc("/api/tiles", s.handleTiles)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./cmd/gateway/ -run HandleTiles`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/cmd/gateway/main.go apps/hil-go/cmd/gateway/tiles_test.go
git commit -m "feat(gateway): handler /api/tiles com cache por sealed"
```

---

## Task 7: gateway — aposentar `handleSeries` e `overview`

**Files:**
- Modify: `apps/hil-go/cmd/gateway/main.go` (remover handleSeries + rota)
- Delete: `apps/hil-go/cmd/gateway/series_handler_test.go`
- Delete: `apps/hil-go/internal/overview/` (pacote inteiro)
- Delete: `apps/hil-go/internal/series/` se não houver outro consumidor (verificar)

- [ ] **Step 1: Confirmar consumidores de series/overview**

Run: `grep -rn "internal/series\|internal/overview" apps/hil-go --include=*.go`
Expected: as únicas referências são `handleSeries` (que vamos remover) e os próprios pacotes/testes.

- [ ] **Step 2: Remover a função `handleSeries` e a rota**

Em `apps/hil-go/cmd/gateway/main.go`, apague a função `handleSeries` inteira (bloco `func (s *server) handleSeries...}`) e a linha de rota:
```go
	mux.HandleFunc("/api/series", s.handleSeries)
```
Remova também o import `"hil.local/daemon/internal/series"` se ficou órfão.

- [ ] **Step 3: Apagar pacotes e teste órfãos**

```bash
git rm apps/hil-go/cmd/gateway/series_handler_test.go
git rm -r apps/hil-go/internal/overview
# Apague internal/series apenas se o Step 1 confirmou que nada mais o usa:
git rm -r apps/hil-go/internal/series
```

- [ ] **Step 4: Compilar e testar todo o backend**

Run: `go build ./... && go test ./...`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A apps/hil-go
git commit -m "refactor(gateway): aposenta handleSeries/overview/series"
```

---

## Task 8: frontend — tipos e decode do tile

**Files:**
- Create: `apps/hil-go/frontend/src/tile.ts`
- Test: `apps/hil-go/frontend/src/tile.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from "vitest";
import { encodeTileForTest, decodeTile, NUM_CH } from "./tile";

describe("decodeTile", () => {
  it("reads header and buckets", () => {
    const buf = encodeTileForTest(0, 0.001, 0.0, [
      { tStart: 0.0, min: filled(-3), max: filled(5), mean: filled(1) },
      { tStart: 0.001, min: filled(2), max: filled(2), mean: filled(2) },
    ]);
    const tile = decodeTile(buf);
    expect(tile.tier).toBe(0);
    expect(tile.bucketSec).toBeCloseTo(0.001);
    expect(tile.t.length).toBe(2);
    expect(tile.min[0][0]).toBe(-3);
    expect(tile.max[0][0]).toBe(5);
    expect(tile.mean[0][1]).toBe(2);
  });
});

function filled(v: number): number[] {
  return new Array(NUM_CH).fill(v);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run (em `apps/hil-go/frontend`): `npm test -- tile`
Expected: FAIL (module not found).

- [ ] **Step 3: Write minimal implementation**

```ts
// Channel order MUST match derive.Channels in the gateway.
export const CHANNEL_NAMES = [
  "Ia", "Ib", "Ic", "FluxA", "FluxB", "FluxC", "Speed", "Te",
] as const;
export const NUM_CH = CHANNEL_NAMES.length;

export interface TileData {
  tier: number;
  bucketSec: number;
  tStart0: number;
  t: number[];
  min: number[][]; // [channel][bucket]
  max: number[][];
  mean: number[][];
}

const HEADER = 13;
const PER_CH = 12;

// decodeTile parses the wire format produced by pyramid.EncodeTile.
export function decodeTile(buf: ArrayBuffer): TileData {
  const dv = new DataView(buf);
  const tier = dv.getUint8(0);
  const count = dv.getUint16(1, true);
  const nch = dv.getUint8(3);
  const bucketSec = dv.getFloat32(4, true);
  const tStart0 = dv.getFloat32(8, true);
  const t: number[] = new Array(count);
  const min: number[][] = Array.from({ length: nch }, () => new Array(count));
  const max: number[][] = Array.from({ length: nch }, () => new Array(count));
  const mean: number[][] = Array.from({ length: nch }, () => new Array(count));
  let off = HEADER;
  for (let i = 0; i < count; i++) {
    t[i] = dv.getFloat32(off, true); off += 4;
    for (let ch = 0; ch < nch; ch++) {
      min[ch][i] = dv.getFloat32(off, true);
      max[ch][i] = dv.getFloat32(off + 4, true);
      mean[ch][i] = dv.getFloat32(off + 8, true);
      off += PER_CH;
    }
  }
  return { tier, bucketSec, tStart0, t, min, max, mean };
}

// encodeTileForTest mirrors the Go encoder so unit tests have golden input.
export function encodeTileForTest(
  tier: number, bucketSec: number, tStart0: number,
  buckets: { tStart: number; min: number[]; max: number[]; mean: number[] }[],
): ArrayBuffer {
  const rec = 4 + NUM_CH * PER_CH;
  const buf = new ArrayBuffer(HEADER + buckets.length * rec);
  const dv = new DataView(buf);
  dv.setUint8(0, tier);
  dv.setUint16(1, buckets.length, true);
  dv.setUint8(3, NUM_CH);
  dv.setFloat32(4, bucketSec, true);
  dv.setFloat32(8, tStart0, true);
  let off = HEADER;
  for (const b of buckets) {
    dv.setFloat32(off, b.tStart, true); off += 4;
    for (let ch = 0; ch < NUM_CH; ch++) {
      dv.setFloat32(off, b.min[ch], true);
      dv.setFloat32(off + 4, b.max[ch], true);
      dv.setFloat32(off + 8, b.mean[ch], true);
      off += PER_CH;
    }
  }
  return buf;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- tile`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/frontend/src/tile.ts apps/hil-go/frontend/src/tile.test.ts
git commit -m "feat(front): tipos e decode do tile"
```

---

## Task 9: frontend — `TileCache` (cache LRU + montagem da janela)

**Files:**
- Create: `apps/hil-go/frontend/src/tilecache.ts`
- Test: `apps/hil-go/frontend/src/tilecache.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect, vi } from "vitest";
import { TileCache } from "./tilecache";
import { encodeTileForTest, NUM_CH } from "./tile";

function fakeTileBytes(tier: number, index: number): ArrayBuffer {
  // One bucket per tile, value = index, bucketSec 0.001, 1024 buckets/tile.
  const tStart = index * 1024 * 0.001;
  const f = (v: number) => new Array(NUM_CH).fill(v);
  return encodeTileForTest(tier, 0.001, tStart, [
    { tStart, min: f(index), max: f(index), mean: f(index) },
  ]);
}

describe("TileCache", () => {
  it("fetches missing tiles and reuses cached ones on pan", async () => {
    const fetcher = vi.fn(async (tier: number, index: number) => ({
      data: fakeTileBytes(tier, index),
      sealed: true,
    }));
    const cache = new TileCache(fetcher, 1024, 100);

    await cache.ensure(0, [0, 1]);
    expect(fetcher).toHaveBeenCalledTimes(2);

    // Pan that needs tile 1 (cached) and 2 (new): only tile 2 is fetched.
    await cache.ensure(0, [1, 2]);
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("always refetches the unsealed trailing tile", async () => {
    const fetcher = vi.fn(async (tier: number, index: number) => ({
      data: fakeTileBytes(tier, index),
      sealed: false,
    }));
    const cache = new TileCache(fetcher, 1024, 100);
    await cache.ensure(0, [0]);
    await cache.ensure(0, [0]);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- tilecache`
Expected: FAIL (module not found).

- [ ] **Step 3: Write minimal implementation**

```ts
import { decodeTile, TileData } from "./tile";

export interface FetchedTile { data: ArrayBuffer; sealed: boolean; }
type TileFetcher = (tier: number, index: number) => Promise<FetchedTile>;

interface Entry { tile: TileData; sealed: boolean; }

// TileCache fetches tiles on demand, keeps sealed ones (LRU-bounded) and always
// refetches the unsealed trailing tile so the live edge stays fresh.
export class TileCache {
  private map = new Map<string, Entry>();
  constructor(
    private fetcher: TileFetcher,
    public bucketsPerTile: number,
    private maxTiles: number,
  ) {}

  private key(tier: number, index: number): string { return `${tier}:${index}`; }

  // ensure guarantees every tile index in `indices` for `tier` is loaded.
  async ensure(tier: number, indices: number[]): Promise<void> {
    await Promise.all(indices.map(async (index) => {
      const k = this.key(tier, index);
      const hit = this.map.get(k);
      if (hit && hit.sealed) { this.touch(k, hit); return; }
      const res = await this.fetcher(tier, index);
      const entry: Entry = { tile: decodeTile(res.data), sealed: res.sealed };
      this.touch(k, entry);
    }));
  }

  // window returns the buckets across `indices` (in order) for rendering.
  window(tier: number, indices: number[]): TileData[] {
    const out: TileData[] = [];
    for (const index of indices) {
      const e = this.map.get(this.key(tier, index));
      if (e) out.push(e.tile);
    }
    return out;
  }

  private touch(k: string, e: Entry): void {
    this.map.delete(k);
    this.map.set(k, e); // re-insert => most recently used
    while (this.map.size > this.maxTiles) {
      const oldest = this.map.keys().next().value as string;
      this.map.delete(oldest);
    }
  }

  clear(): void { this.map.clear(); }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- tilecache`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/frontend/src/tilecache.ts apps/hil-go/frontend/src/tilecache.test.ts
git commit -m "feat(front): TileCache com LRU e refetch do tile vivo"
```

---

## Task 10: frontend — `ViewportController` reescrito (tier + tiles + descarte de obsoletos)

**Files:**
- Modify: `apps/hil-go/frontend/src/viewport.ts`
- Test: `apps/hil-go/frontend/src/viewport.test.ts` (substitui o conteúdo atual)

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect, vi } from "vitest";
import { ViewportController, indicesForWindow, selectTier } from "./viewport";

describe("selectTier", () => {
  const tiers = [
    { tier: 0, bucketSec: 0.001 },
    { tier: 1, bucketSec: 0.020 },
    { tier: 2, bucketSec: 0.500 },
    { tier: 3, bucketSec: 10.0 },
  ];
  it("picks the coarsest tier that still gives >=1 bucket/pixel", () => {
    expect(selectTier(tiers, 0.0001)).toBe(-1); // raw
    expect(selectTier(tiers, 0.002)).toBe(0);
    expect(selectTier(tiers, 0.6)).toBe(2);
    expect(selectTier(tiers, 100)).toBe(3);
  });
});

describe("indicesForWindow", () => {
  it("maps a time window to tile indices", () => {
    // bucketSec 0.001, 1024 buckets/tile => tile covers 1.024 s.
    expect(indicesForWindow(0.001, 1024, 0.0, 2.0)).toEqual([0, 1]);
    expect(indicesForWindow(0.001, 1024, 1.1, 1.2)).toEqual([1]);
  });
});

describe("ViewportController", () => {
  it("discards a response whose window is no longer current", async () => {
    let resolveFirst: (v: number[]) => void = () => {};
    const onData = vi.fn();
    const ctl = new ViewportController(async (from) => {
      if (from === 0) return new Promise<number[]>((r) => { resolveFirst = r; });
      return [from];
    }, 0);
    ctl.onData = onData;

    ctl.request(0, 1, 800);     // slow, will resolve late
    ctl.request(5, 6, 800);     // newer window
    await Promise.resolve();
    resolveFirst([0]);          // late response from the stale window
    await Promise.resolve(); await Promise.resolve();

    // onData must only ever be called with the newest window's data.
    for (const call of onData.mock.calls) {
      expect(call[0]).not.toEqual([0]);
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- viewport`
Expected: FAIL (new exports not defined).

- [ ] **Step 3: Write minimal implementation**

Substitua todo o conteúdo de `apps/hil-go/frontend/src/viewport.ts` por:

```ts
export interface TierMeta { tier: number; bucketSec: number; }

// selectTier mirrors pyramid.SelectTier: coarsest tier whose bucket <= secPerPx,
// or -1 when even the finest tier is coarser than the zoom (use raw T0).
export function selectTier(tiers: TierMeta[], secPerPx: number): number {
  let best = -1;
  for (const t of tiers) {
    if (t.bucketSec <= secPerPx) best = t.tier;
  }
  return best;
}

// indicesForWindow returns the tile indices covering [from,to] for a tier.
export function indicesForWindow(
  bucketSec: number, bucketsPerTile: number, from: number, to: number,
): number[] {
  const tileSec = bucketSec * bucketsPerTile;
  const first = Math.max(0, Math.floor(from / tileSec));
  const last = Math.max(first, Math.floor(to / tileSec));
  const out: number[] = [];
  for (let i = first; i <= last; i++) out.push(i);
  return out;
}

type Fetcher<T> = (from: number, to: number, width: number) => Promise<T>;

// ViewportController debounces zoom/pan into a single query and only delivers a
// response if its window is still the current one (kills the stale-range race).
export class ViewportController<T = unknown> {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pending: [number, number, number] | null = null;
  private seq = 0;
  onData: (data: T) => void = () => {};

  constructor(private fetcher: Fetcher<T>, private debounceMs = 60) {}

  request(from: number, to: number, width: number): void {
    this.seq++;
    this.pending = [from, to, width];
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush(), this.debounceMs);
  }

  private async flush(): Promise<void> {
    if (!this.pending) return;
    const [from, to, width] = this.pending;
    this.pending = null;
    const seq = this.seq;
    const data = await this.fetcher(from, to, width);
    if (seq !== this.seq) return; // a newer window superseded this one
    this.onData(data);
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- viewport`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/frontend/src/viewport.ts apps/hil-go/frontend/src/viewport.test.ts
git commit -m "feat(front): ViewportController por tier/tiles com descarte de obsoleto"
```

---

## Task 11: frontend — caminho de render único no `main.ts`

**Files:**
- Modify: `apps/hil-go/frontend/src/main.ts`

> Este task troca a fonte de dados do render para a pirâmide de tiles. Faça em passos pequenos e rode `npm run build` ao final de cada sub-passo grande.

- [ ] **Step 1: Buscar metadados de tiers no boot**

No topo de `main.ts`, perto dos outros imports (linha ~7), troque o import do viewport e adicione os novos:
```ts
import { ViewportController, selectTier, indicesForWindow, TierMeta } from "./viewport";
import { TileCache, FetchedTile } from "./tilecache";
import { decodeTile, TileData, NUM_CH } from "./tile";
```

Adicione, perto da declaração de `seriesViewport` (linha ~828), o estado da pirâmide:
```ts
let tierMeta: TierMeta[] = [];
let bucketsPerTile = 1024;
let tilesActive = false;
let latestTiles: TileData[] = [];

async function loadTierMeta(): Promise<void> {
  try {
    const res = await fetch(gatewayURL("/api/tiers"), { cache: "no-store" });
    if (!res.ok) return;
    const meta = await res.json();
    tierMeta = meta.tiers as TierMeta[];
    bucketsPerTile = meta.bucketsPerTile ?? 1024;
  } catch { /* gateway not ready yet */ }
}

const tileCache = new TileCache(
  async (tier, index): Promise<FetchedTile> => {
    const res = await fetch(gatewayURL(`/api/tiles?tier=${tier}&index=${index}`), { cache: "default" });
    return { data: await res.arrayBuffer(), sealed: res.headers.get("Cache-Control")?.includes("immutable") ?? false };
  },
  bucketsPerTile, 200,
);
```

- [ ] **Step 2: Substituir o controller de viewport pela versão de tiles**

Troque o bloco `const seriesViewport = new ViewportController(... )` e seu `seriesViewport.onData` (linhas ~828-844) por:
```ts
const tileViewport = new ViewportController<TileData[]>(async (from, to, width) => {
  if (tierMeta.length === 0) await loadTierMeta();
  const secPerPx = (to - from) / Math.max(1, width);
  const tIdx = selectTier(tierMeta, secPerPx);
  if (tIdx < 0) return []; // raw: render direto do tBuf (Step 4)
  const meta = tierMeta[tIdx];
  const indices = indicesForWindow(meta.bucketSec, bucketsPerTile, from, to);
  await tileCache.ensure(tIdx, indices);
  return tileCache.window(tIdx, indices);
}, 60);
tileViewport.onData = (tiles) => {
  latestTiles = tiles;
  tilesActive = tiles.length > 0;
  scheduleRender();
};
```

- [ ] **Step 3: Trocar a projeção de série por projeção de tiles**

Substitua a função `seriesToProjected` (linhas ~850-888) por `tilesToProjected`:
```ts
// Flatten loaded tiles into AlignedData: min/max vertical strokes per bucket
// (raw envelope) plus a mean centerline, in the live CHANNELS order.
function tilesToProjected(tiles: TileData[]): { xs: number[]; ys: number[][] } {
  let n = 0;
  for (const t of tiles) n += t.t.length;
  const xs: number[] = new Array(n * 2);
  const ys: number[][] = CHANNELS.map(() => new Array<number>(n * 2));
  const tl = Number(elTorque.value) || 0;
  let w = 0;
  for (const tile of tiles) {
    for (let i = 0; i < tile.t.length; i++) {
      const base = w * 2;
      xs[base] = tile.t[i];
      xs[base + 1] = tile.t[i];
      for (let k = 0; k < CHANNELS.length; k++) {
        const si = PLOT_TO_SERIES[CHANNELS[k].name];
        if (si === undefined) {
          const v = CHANNELS[k].name === "TL" ? tl : NaN;
          ys[k][base] = v; ys[k][base + 1] = v;
          continue;
        }
        let mn = tile.min[si][i], mx = tile.max[si][i];
        if (CHANNELS[k].name === "Speed") { mn *= RPM_PER_RAD_S; mx *= RPM_PER_RAD_S; }
        ys[k][base] = mn;
        ys[k][base + 1] = mx;
      }
      w++;
    }
  }
  return { xs, ys };
}
```

(Mantenha `PLOT_TO_SERIES` e `RPM_PER_RAD_S` como estão; eles continuam válidos.)

- [ ] **Step 4: Atualizar o setInterval de polling do viewport**

Substitua o `setInterval(() => { ... seriesViewport.request ... }, 100)` (linhas ~893-901) por:
```ts
setInterval(() => {
  if (plots.length === 0 || displayMode !== "abc") return;
  const hiResStart = tBuf.length > 0 ? tBuf[0] : Infinity;
  const viewEnd = viewEndSec;
  const viewStart = Math.max(0, viewEnd - windowSec);
  if (!paused || viewStart >= hiResStart) return; // dentro do tail raw: render local
  const w = elPlotArea.clientWidth || 800;
  tileViewport.request(viewStart, viewEnd, Math.max(600, w * 2));
}, 100);
```

- [ ] **Step 5: Religar o render em `scheduleRender`**

No `scheduleRender` (linhas ~2305-2310), troque o bloco de seleção de fonte:
```ts
    const needHistoricalSeries = paused && viewStart < hiResStart;
    const useSeries = needHistoricalSeries && seriesActive && displayMode === "abc"
      && latestSeries != null && latestSeries.t.length > 0;
    const { xs, ys } = useSeries
      ? seriesToProjected(latestSeries!)
      : decimateAndProject(maxPts, viewStart, viewEnd);
```
por:
```ts
    const needHistorical = paused && viewStart < hiResStart;
    const useTiles = needHistorical && tilesActive && displayMode === "abc" && latestTiles.length > 0;
    const { xs, ys } = useTiles
      ? tilesToProjected(latestTiles)
      : decimateAndProject(maxPts, viewStart, viewEnd);
```

- [ ] **Step 6: Carregar metadados no boot e ao dar Run/reset**

Encontre a inicialização (onde `pollRawTelemetry` é iniciado ou no fim do boot) e adicione uma chamada `loadTierMeta();`. No handler de reset/run do front (onde `streamGeneration++` ocorre, linha ~2627), adicione:
```ts
  tileCache.clear();
  tierMeta = [];
  latestTiles = [];
  tilesActive = false;
```

- [ ] **Step 7: Build**

Run (em `apps/hil-go/frontend`): `npm run build`
Expected: PASS (sem erros de tipo). Corrija referências remanescentes a `seriesToProjected`/`latestSeries`/`seriesActive` apontando-as para os novos nomes (serão removidas na Task 13).

- [ ] **Step 8: Commit**

```bash
git add apps/hil-go/frontend/src/main.ts
git commit -m "feat(front): render historico via tiles da piramide"
```

---

## Task 12: frontend — pausa-ao-navegar e botão "Voltar ao vivo"

**Files:**
- Modify: `apps/hil-go/frontend/src/main.ts`

- [ ] **Step 1: Garantir freeze ao navegar**

Confirme que toda entrada de navegação (wheel no plot, drag na timeline) chama `freezeTimelineView()` antes de mexer em `windowSec`/`viewEndSec`. A timeline já chama (`beginDrag`/`pointerdown` em `attachTimelineNavigation`). Para o wheel no plot, localize o handler de wheel (busque `wheel` em `main.ts`) e garanta `freezeTimelineView()` na primeira linha dele.

- [ ] **Step 2: Adicionar o botão "Voltar ao vivo"**

No HTML do painel de telemetria, perto do `#btn-pause` (linha ~700), adicione:
```html
<button id="btn-live" class="btn btn-sm" title="Regrudar a borda direita ao tempo real">⏵ Ao vivo</button>
```

- [ ] **Step 3: Ligar o botão**

Perto da fiação dos outros botões do plot, adicione:
```ts
const elBtnLive = document.querySelector<HTMLButtonElement>("#btn-live")!;
elBtnLive.onclick = () => {
  paused = false;
  if (tBuf.length) viewEndSec = tBuf[tBuf.length - 1];
  tilesActive = false;
  latestTiles = [];
  scheduleRender();
};
```

- [ ] **Step 4: Build e teste**

Run: `npm run build && npm test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/frontend/src/main.ts
git commit -m "feat(front): pausa ao navegar + botao Voltar ao vivo"
```

---

## Task 13: frontend — remover o pipeline antigo

**Files:**
- Modify: `apps/hil-go/frontend/src/main.ts`
- Delete: `apps/hil-go/frontend/src/series.ts`, `apps/hil-go/frontend/src/series.test.ts`

- [ ] **Step 1: Remover símbolos órfãos**

Em `main.ts`, remova: a importação de `./series` (`decodeSeries`, `SeriesColumns`, `fetchSeries`), as variáveis `latestSeries`, `seriesActive`, `ovTBuf`, `ovSBuf` e qualquer função que só as use (ex.: a parte de `decimateAndProject` que roteava para `ovTBuf`/`ovSBuf` pode ser simplificada para usar só `tBuf`/`samplesBuf`, já que o histórico agora vem dos tiles).

- [ ] **Step 2: Confirmar que não há referência restante**

Run: `grep -n "latestSeries\|seriesActive\|ovTBuf\|ovSBuf\|seriesToProjected\|fetchSeries\|decodeSeries" apps/hil-go/frontend/src/main.ts`
Expected: nenhuma saída.

- [ ] **Step 3: Apagar o módulo series do front**

```bash
git rm apps/hil-go/frontend/src/series.ts apps/hil-go/frontend/src/series.test.ts
```

- [ ] **Step 4: Build e teste completos**

Run (em `apps/hil-go/frontend`): `npm run build && npm test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A apps/hil-go/frontend
git commit -m "refactor(front): remove pipeline series/overview antigo"
```

---

## Task 14: verificação integrada

**Files:** nenhum (verificação manual + suíte).

- [ ] **Step 1: Suíte completa backend + front**

Run: `cd apps/hil-go && go test ./... && cd frontend && npm test && npm run build`
Expected: tudo PASS.

- [ ] **Step 2: Subir o gateway e validar os endpoints novos**

```bash
cd apps/hil-go && go run ./cmd/gateway &
sleep 1
curl -s http://127.0.0.1:5177/api/tiers | head -c 400
curl -s -D - -o /dev/null "http://127.0.0.1:5177/api/tiles?tier=0&index=0"
```
Expected: `/api/tiers` retorna JSON com 4 tiers; `/api/tiles` retorna 200 com `Content-Type: application/octet-stream` e um `Cache-Control` (no-store enquanto não há dado/ponta).

- [ ] **Step 3: Validação visual (com placa ou replay de telemetria)**

Abra `http://127.0.0.1:5177`, dê Run, espere acumular alguns segundos, pause e:
- Arraste/zoom pela timeline cobrindo toda a sessão: o traço deve seguir o mouse sem lag perceptível.
- Cruze a fronteira do tail raw (~6 s atrás): o traço não deve mudar de caráter nem sumir.
- Faça pan de ida e volta: sem flicker nem regiões em branco (tiles reusados do cache).
- Clique "Ao vivo": a borda direita regruda ao tempo real.

- [ ] **Step 4: Commit final (se houve ajuste)**

```bash
git add -A apps/hil-go
git commit -m "test: verificacao integrada do pipeline de tiles"
```

---

## Self-Review (preenchido pelo autor do plano)

- **Cobertura do spec:** tiers/Push/SelectTier/Tile (Tasks 1-2), formato wire (Task 3), ingestão na pirâmide (Task 4), `/api/tiers` e `/api/tiles` com cache (Tasks 5-6), aposentar handleSeries/overview (Task 7), decode/cache/viewport no front (Tasks 8-10), render único (Task 11), pausa-ao-navegar + Ao vivo (Task 12), limpeza (Task 13), verificação (Task 14). Fora do Plano 1 por decisão de escopo: visualizar runs salvos e `BuildFromStore` (Plano 2).
- **Consistência de tipos:** `Bucket{TStart,Min,Max,Mean,Count}`, `EncodeTile(tier,bucketSec,tStart0,buckets)`, `decodeTile -> TileData{tier,bucketSec,tStart0,t,min,max,mean}`, `TileCache.ensure/window`, `selectTier/indicesForWindow` batem entre Go e TS.
- **Placeholders:** nenhum; todo passo de código mostra o código.
