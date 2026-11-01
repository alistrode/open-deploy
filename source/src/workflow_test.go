package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func stateKey(s FlowState) string { b, _ := json.Marshal(s); return string(b) }
func assertFlowSafety(t *testing.T, s FlowState) {
	t.Helper()
	if s.Activations > 3 || s.Attempts > 3 {
		t.Fatal("activation/reboot bound", s)
	}
	switch s.Phase {
	case "installing", "installed", "drivers", "complete":
		if s.Proofs&FactMedia == 0 {
			t.Fatal("install before prepared", s)
		}
	}
	switch s.Phase {
	case "installed", "drivers", "complete":
		if s.Proofs&(FactImage|FactBoot|FactHandoff) != (FactImage | FactBoot | FactHandoff) {
			t.Fatal("unproven install", s)
		}
	}
	if s.Phase == "complete" && (s.Proofs&FactHealthy == 0 || s.Activations != 3) {
		t.Fatal("false completion", s)
	}
}
func TestExhaustiveRuntimeWorkflow(t *testing.T) {
	hash := strings.Repeat("a", 64)
	start := FlowState{Schema: 1, PlanSHA256: hash, Phase: "configured"}
	queue := []FlowState{start}
	seen := map[string]bool{stateKey(start): true}
	edges, rejections := 0, 0
	actions := []string{"fail"}
	for _, rule := range workflowDefinition().Transitions {
		actions = append(actions, rule.Action)
	}
	for len(queue) > 0 {
		s := queue[0]
		queue = queue[1:]
		assertFlowSafety(t, s)
		for _, action := range actions {
			for facts := uint16(0); facts < 512; facts++ {
				if _, err := advanceFlow(s, action, facts, strings.Repeat("b", 64)); err == nil {
					t.Fatal("plan drift accepted")
				}
				n, e := advanceFlow(s, action, facts, hash)
				if e != nil {
					rejections++
					continue
				}
				edges++
				assertFlowSafety(t, n)
				if n.Activations-s.Activations > 1 {
					t.Fatal("multiple manual actions in one transition")
				}
				if action == "drivers.resume" && n.Activations != s.Activations {
					t.Fatal("reboot requires another manual activation")
				}
				k := stateKey(n)
				if !seen[k] {
					seen[k] = true
					queue = append(queue, n)
				}
			}
		}
	}
	if path := os.Getenv("OPENDEPLOY_FORMAL_STATES"); path != "" {
		projection := []map[string]any{}
		for key := range seen {
			var state FlowState
			_ = json.Unmarshal([]byte(key), &state)
			projection = append(projection, map[string]any{"phase": state.Phase, "activations": state.Activations, "attempts": state.Attempts, "proofs": state.Proofs})
		}
		data, _ := json.MarshalIndent(projection, "", "  ")
		if err := os.WriteFile(path, data, 0600); err != nil {
			t.Fatal(err)
		}
	}
	t.Logf("exhaustive runtime: %d states, %d accepted edges, %d rejected fact/action pairs; all changed-plan requests rejected", len(seen), edges, rejections)
	if len(seen) < 10 || edges == 0 || rejections == 0 {
		t.Fatal("vacuous exploration")
	}
}
func TestThreeActivationsWithAutomaticReboots(t *testing.T) {
	hash := strings.Repeat("a", 64)
	s := FlowState{Schema: 1, PlanSHA256: hash, Phase: "configured"}
	actions := []string{"prepare.start", "prepare.done", "install.start", "install.done", "drivers.start", "drivers.resume", "drivers.resume", "drivers.done"}
	facts := []uint16{7, 9, 11, 113, 67, 67, 67, 195}
	for i, a := range actions {
		var e error
		s, e = advanceFlow(s, a, facts[i], hash)
		if e != nil {
			t.Fatal(a, e)
		}
	}
	if s.Phase != "complete" || s.Activations != 3 || s.Attempts != 3 {
		t.Fatal(s)
	}
	if _, e := advanceFlow(s, "prepare.start", 7, hash); e == nil {
		t.Fatal("complete plan reactivated")
	}
}
func TestDiskBindingSurvivesReorderingAndRejectsAmbiguity(t *testing.T) {
	id := DiskIdentity{Serial: "approved", Size: 128 << 30, USB: false}
	disk, e := resolveDisk(id, []Disk{{9, "disk", "other", 128 << 30, false}, {4, "disk", "approved", 128 << 30, false}})
	if e != nil || disk.Number != 4 {
		t.Fatal("disk index used as identity", disk, e)
	}
	for _, ds := range [][]Disk{{}, {{0, "disk", "approved", 128 << 30, true}}, {{1, "disk", "approved", 128 << 30, false}, {2, "disk", "approved", 128 << 30, false}}} {
		if _, e = resolveDisk(id, ds); e == nil {
			t.Fatal("unsafe binding accepted", ds)
		}
	}
}
func TestSealedPlanRejectsEditsAndDuplicateKeys(t *testing.T) {
	p := ExecutionPlan{Schema: 1, ID: "12345678-1234-1234-1234-123456789abc", MachineUUID: "12345678-1234-1234-1234-123456789abd", ISOPath: filepath.Join(t.TempDir(), "Windows.iso"), ISOSHA256: strings.Repeat("a", 64), ImageIndex: 2, USB: DiskIdentity{"usb", 32 << 30, true}, Target: DiskIdentity{"target", 128 << 30, false}, DriversSHA256: strings.Repeat("b", 64), EraseUSB: true, EraseTarget: true}
	path := filepath.Join(t.TempDir(), "plan.json")
	if e := writeJSONAtomic(path, p); e != nil {
		t.Fatal(e)
	}
	if _, _, e := loadPlan(path); e != nil {
		t.Fatal(e)
	}
	good, _ := os.ReadFile(path)
	bad := strings.Replace(string(good), "{", "{\n\"image_index\":1,", 1)
	os.WriteFile(path, []byte(bad), 0600)
	if _, _, e := loadPlan(path); e == nil {
		t.Fatal("ambiguous duplicate key accepted")
	}
	p.EraseTarget = false
	os.WriteFile(path, canonicalJSON(p), 0600)
	if _, _, e := loadPlan(path); e == nil {
		t.Fatal("missing preapproval accepted")
	}
}
func TestInstalledAndHealthyGuardsCannotBeSkipped(t *testing.T) {
	hash := strings.Repeat("a", 64)
	s := FlowState{Schema: 1, PlanSHA256: hash, Phase: "installing", Activations: 2, Proofs: 15}
	if _, e := advanceFlow(s, "install.done", FactPlan|FactImage|FactHandoff, hash); e == nil {
		t.Fatal("missing boot proof accepted")
	}
	s.Phase = "drivers"
	s.Activations = 3
	s.Attempts = 3
	s.Proofs = 127
	for _, facts := range []uint16{FactPlan | FactBound | FactHandoff, FactPlan | FactBound | FactHandoff | FactHealthy | FactPending} {
		if _, e := advanceFlow(s, "drivers.done", facts, hash); e == nil {
			t.Fatal("false success")
		}
	}
	if _, e := advanceFlow(s, "drivers.resume", 67, hash); e == nil {
		t.Fatal("unbounded reboot")
	}
}

func TestConfigureSealsActualInputsAndRefusesCorruptJournal(t *testing.T) {
	root := t.TempDir()
	iso := filepath.Join(root, "Windows.iso")
	os.WriteFile(iso, []byte("fixture ISO bytes"), 0600)
	os.WriteFile(filepath.Join(root, "drivers-manifest.json"), []byte("fixture manifest"), 0600)
	ih, _ := hashFile(iso)
	dh, _ := hashFile(filepath.Join(root, "drivers-manifest.json"))
	p := ExecutionPlan{Schema: 1, MachineUUID: "12345678-1234-1234-1234-123456789abd", ISOPath: iso, ISOSHA256: ih, ImageIndex: 1, USB: DiskIdentity{"usb", 32 << 30, true}, Target: DiskIdentity{"ssd", 128 << 30, false}, DriversSHA256: dh, EraseUSB: true, EraseTarget: true}
	spec := filepath.Join(root, "spec.json")
	plan := filepath.Join(root, "plan.json")
	os.WriteFile(spec, canonicalJSON(p), 0600)
	inventory := []Disk{{7, "USB", "usb", 32 << 30, true}}
	if err := configureWithInventory(spec, plan, root, inventory); err != nil {
		t.Fatal(err)
	}
	sealed, h, err := loadPlan(plan)
	if err != nil || !validUUID(sealed.ID) {
		t.Fatal(sealed, err)
	}
	flow, err := loadFlow(journalPath(plan))
	if err != nil || flow.Phase != "configured" || flow.PlanSHA256 != h {
		t.Fatal(flow, err)
	}
	os.WriteFile(journalPath(plan), []byte("corrupt"), 0600)
	if err := configureWithInventory(spec, plan, root, inventory); err == nil {
		t.Fatal("corrupt journal silently replaced")
	}
	os.Remove(journalPath(plan))
	os.WriteFile(iso, []byte("changed"), 0600)
	if err := configureWithInventory(spec, plan, root, inventory); err == nil {
		t.Fatal("changed ISO approved")
	}
}
func TestFactMappingMatchesFormalDefinition(t *testing.T) {
	expected := map[string]uint16{"plan": FactPlan, "bound": FactBound, "inputs": FactInputs, "media": FactMedia, "image": FactImage, "boot": FactBoot, "handoff": FactHandoff, "healthy": FactHealthy, "pending": FactPending}
	actual := workflowDefinition().Facts
	if len(actual) != len(expected) {
		t.Fatal(actual)
	}
	for key, value := range expected {
		if actual[key] != value {
			t.Fatal(key, actual[key], value)
		}
	}
}
