package main

import (
	"bytes"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

//go:embed workflow.json
var workflowTable []byte

const (
	FactPlan    uint16 = 1
	FactBound   uint16 = 2
	FactInputs  uint16 = 4
	FactMedia   uint16 = 8
	FactImage   uint16 = 16
	FactBoot    uint16 = 32
	FactHandoff uint16 = 64
	FactHealthy uint16 = 128
	FactPending uint16 = 256
)

type Transition struct {
	Action, From, To     string
	Required, Forbidden  uint16
	Activations, Attempt int
}
type WorkflowDefinition struct {
	Facts       map[string]uint16
	Transitions []Transition
}

func workflowDefinition() WorkflowDefinition {
	var d WorkflowDefinition
	if err := json.Unmarshal(workflowTable, &d); err != nil {
		panic(err)
	}
	return d
}

type FlowState struct {
	Schema      int    `json:"schema"`
	PlanSHA256  string `json:"plan_sha256"`
	Phase       string `json:"phase"`
	Activations int    `json:"activations"`
	Attempts    int    `json:"attempts"`
	Proofs      uint16 `json:"proofs"`
	ImageName   string `json:"image_name,omitempty"`
	ImageSHA256 string `json:"image_sha256,omitempty"`
	Error       string `json:"error,omitempty"`
}

// advanceFlow is the only implementation of phase transitions. Both the
// runtime and the independently checked TLA+ specification use workflow.json.
func advanceFlow(s FlowState, action string, facts uint16, hash string) (FlowState, error) {
	if err := validateFlowState(s); err != nil {
		return s, err
	}
	if hash != s.PlanSHA256 || !validHash(hash) {
		return s, errors.New("sealed plan changed")
	}
	if s.Schema != 1 || s.Activations < 0 || s.Activations > 3 || s.Attempts < 0 || s.Attempts > 3 {
		return s, errors.New("invalid workflow state")
	}
	if action == "fail" {
		if s.Phase == "complete" || s.Phase == "failed" {
			return s, errors.New("terminal workflow")
		}
		s.Phase = "failed"
		return s, nil
	}
	for _, t := range workflowDefinition().Transitions {
		if t.Action != action || t.From != s.Phase {
			continue
		}
		if facts&t.Required != t.Required || facts&t.Forbidden != 0 {
			return s, errors.New("stage contract not satisfied")
		}
		if t.Activations < s.Activations || t.Activations > s.Activations+1 {
			return s, errors.New("invalid activation order")
		}
		if action == "drivers.resume" && s.Attempts >= 3 {
			return s, errors.New("driver restart limit reached")
		}
		s.Phase = t.To
		s.Activations = t.Activations
		s.Attempts += t.Attempt
		s.Proofs |= t.Required &^ FactPending
		return s, nil
	}
	return s, fmt.Errorf("action %s is not enabled in %s", action, s.Phase)
}
func validateFlowState(s FlowState) error {
	if s.Schema != 1 || !validHash(s.PlanSHA256) || s.Activations < 0 || s.Activations > 3 || s.Attempts < 0 || s.Attempts > 3 {
		return errors.New("corrupt workflow journal")
	}
	required := map[string]struct {
		activations int
		proofs      uint16
	}{"configured": {0, 0}, "preparing": {1, 7}, "prepared": {1, 15}, "installing": {2, 15}, "installed": {2, 127}, "drivers": {3, 127}, "complete": {3, 255}}
	if s.Phase == "failed" {
		switch s.Proofs {
		case 0, 7, 15, 127:
			return nil
		}
		return errors.New("corrupt failed receipt")
	}
	expected, ok := required[s.Phase]
	if !ok || expected.activations != s.Activations || expected.proofs != s.Proofs {
		return errors.New("phase, activation count and proofs disagree")
	}
	if (s.Phase == "drivers" || s.Phase == "complete") && s.Attempts < 1 {
		return errors.New("driver phase was not activated")
	}
	if s.Phase != "drivers" && s.Phase != "complete" && s.Attempts != 0 {
		return errors.New("invalid driver attempts")
	}
	return nil
}
func validHash(s string) bool {
	b, e := hex.DecodeString(s)
	return e == nil && len(b) == 32 && s == strings.ToLower(s)
}
func hashFile(path string) (string, error) {
	f, e := os.Open(path)
	if e != nil {
		return "", e
	}
	defer f.Close()
	h := sha256.New()
	if _, e = io.Copy(h, f); e != nil {
		return "", e
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}
func writeJSONAtomic(path string, v any) error {
	b, e := json.MarshalIndent(v, "", "  ")
	if e != nil {
		return e
	}
	b = append(b, '\n')
	f, e := os.OpenFile(path+".new", os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0600)
	if e != nil {
		return e
	}
	if _, e = f.Write(b); e == nil {
		e = f.Sync()
	}
	ce := f.Close()
	if e == nil {
		e = ce
	}
	if e != nil {
		return e
	}
	return replaceStateFile(path+".new", path)
}
func loadFlow(path string) (FlowState, error) {
	var s FlowState
	b, e := os.ReadFile(path)
	if e == nil {
		e = strictJSON(b, &s)
	}
	if e == nil {
		e = validateFlowState(s)
	}
	return s, e
}
func canonicalJSON(v any) []byte { b, _ := json.MarshalIndent(v, "", "  "); return append(b, '\n') }
func strictJSON(data []byte, v any) error {
	d := json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	if e := d.Decode(v); e != nil {
		return e
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return errors.New("extra JSON content")
	}
	return nil
}
func journalPath(planPath string) string {
	return filepath.Join(filepath.Dir(planPath), "flow-state.json")
}
