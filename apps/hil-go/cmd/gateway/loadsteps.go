package main

import "net/http"

type loadStep struct {
	T     float64 `json:"t"`
	Value float64 `json:"value"`
}

func (s *server) recordLoadCommand(value float64) {
	s.ingestMu.Lock()
	defer s.ingestMu.Unlock()
	s.loadNm = value
	t := 0.0
	if s.store != nil {
		_, t = s.store.Span()
	}
	if n := len(s.loadSteps); n > 0 && s.loadSteps[n-1].T == t {
		s.loadSteps[n-1].Value = value
		return
	}
	s.loadSteps = append(s.loadSteps, loadStep{T: t, Value: value})
}

func (s *server) handleLoadSteps(w http.ResponseWriter, _ *http.Request) {
	s.ingestMu.Lock()
	steps := append([]loadStep(nil), s.loadSteps...)
	s.ingestMu.Unlock()
	if steps == nil {
		steps = []loadStep{}
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, steps)
}
