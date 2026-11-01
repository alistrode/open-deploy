package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

func persistAdvance(path string, s FlowState, action string, facts uint16, hash string) (FlowState, error) {
	next, e := advanceFlow(s, action, facts, hash)
	if e != nil {
		return s, e
	}
	e = writeJSONAtomic(path, next)
	return next, e
}
func validateConfiguredContext(planPath, stage, root string) (ExecutionPlan, string, FlowState, error) {
	p, h, e := loadPlan(planPath)
	if e != nil {
		return p, h, FlowState{}, e
	}
	s, e := loadFlow(journalPath(planPath))
	if e != nil {
		return p, h, s, e
	}
	if s.PlanSHA256 != h {
		return p, h, s, errors.New("plan does not match the persisted operation")
	}
	if h, e := hashFile(filepath.Join(root, "drivers-manifest.json")); e != nil || h != p.DriversSHA256 {
		return p, "", s, errors.New("driver manifest changed")
	}
	if stage != "prepare" {
		uuid, e := machineUUID()
		if e != nil || !strings.EqualFold(uuid, p.MachineUUID) {
			return p, h, s, errors.New("this is not the preconfigured target computer")
		}
	}
	if stage == "drivers" {
		target, err := resolveDisk(p.Target, listDisks())
		if err != nil {
			return p, h, s, err
		}
		if volumeDisk(os.Getenv("SystemDrive")) != target.Number {
			return p, h, s, errors.New("running system disk differs from preconfigured target")
		}
	}
	return p, h, s, nil
}

func runConfiguredStage(planPath, stage, root string, resume bool) (result error) {
	p, h, s, e := validateConfiguredContext(planPath, stage, rootForPlan(stage, root, planPath))
	if e != nil {
		return e
	}
	unlock, e := lockWorkflow(h)
	if e != nil {
		return e
	}
	defer unlock()
	// Reload under the lifetime lock. No second worker may use the old phase.
	s, e = loadFlow(journalPath(planPath))
	if e != nil {
		return e
	}
	options := Options{Root: root, ISO: p.ISOPath, Index: p.ImageIndex, Stage: stage, Live: true, Consent: true, PlanFile: planPath, Resume: resume}
	facts := FactPlan | FactBound
	switch stage {
	case "prepare":
		if resume {
			return errors.New("only driver reboot recovery can resume")
		}
		if isPE() {
			return errors.New("preparation requires host Windows")
		}
		options.USB, e = resolveDisk(p.USB, listDisks())
		if e != nil {
			return e
		}
		if digest, err := hashFile(p.ISOPath); err != nil || digest != p.ISOSHA256 {
			return errors.New("ISO no longer matches sealed plan")
		}
		if e = verifyBootstrap(root); e != nil {
			return e
		}
		facts |= FactInputs
	case "install":
		if resume || !isPE() {
			return errors.New("installation requires preconfigured PE")
		}
		options.Target, e = resolveDisk(p.Target, listDisks())
		if e != nil {
			return e
		}
		media := filepath.Dir(filepath.Dir(planPath))
		if s.ImageName != "Windows.wim" && s.ImageName != "Windows.esd" {
			return errors.New("prepared image receipt missing")
		}
		if digest, err := hashFile(filepath.Join(media, "Images", s.ImageName)); err != nil || digest != s.ImageSHA256 {
			return errors.New("prepared image changed after stage one")
		}
		if e = verifyBootstrap(filepath.Dir(planPath)); e != nil {
			return e
		}
		facts |= FactMedia
	case "drivers":
		if isPE() {
			return errors.New("drivers require the installed Windows")
		}
		currentTarget, err := resolveDisk(p.Target, listDisks())
		if err != nil {
			return err
		}
		if volumeDisk(os.Getenv("SystemDrive")) != currentTarget.Number {
			return errors.New("running Windows is not on the approved target")
		}
		if e = checkDeploymentReceipt(root, h); e != nil {
			return e
		}
		facts |= FactHandoff
	default:
		return errors.New("unknown configured stage")
	}
	action := stage + ".start"
	if resume {
		action = "drivers.resume"
	}
	s, e = persistAdvance(journalPath(planPath), s, action, facts, h)
	if e != nil {
		if resume && s.Phase == "drivers" && s.Attempts >= 3 {
			failed, err := advanceFlow(s, "fail", FactPlan, h)
			if err == nil {
				failed.Error = e.Error()
				_ = writeJSONAtomic(journalPath(planPath), failed)
			}
		}
		return e
	}
	defer func() {
		if result != nil && !errors.Is(result, ErrStagePending) {
			current, err := loadFlow(journalPath(planPath))
			if err == nil && current.Phase != "complete" && current.Phase != "failed" {
				failed, err := advanceFlow(current, "fail", FactPlan, h)
				if err == nil {
					failed.Error = result.Error()
					_ = writeJSONAtomic(journalPath(planPath), failed)
				}
			}
		}
	}()
	engine := Engine{Options: options, Runner: liveRunner, Output: func(message string) { fmt.Println(message) }}
	switch stage {
	case "prepare":
		e = engine.Prepare()
	case "install":
		e = engine.Install()
	case "drivers":
		e = engine.Drivers()
	}
	if errors.Is(e, ErrStagePending) {
		return e
	}
	if e != nil {
		// A reboot can terminate this process; only an observed returned error is
		// recorded as failed. A new boot resumes the persisted driver phase.
		failed, err := advanceFlow(s, "fail", FactPlan, h)
		if err == nil {
			failed.Error = e.Error()
			_ = writeJSONAtomic(journalPath(planPath), failed)
		}
		return e
	}
	switch stage {
	case "prepare":
		media := engine.Options.MediaRoot
		if media == "" {
			return errors.New("preparation returned no verified media")
		}
		b, err := os.ReadFile(filepath.Join(media, "OpenDeploy", "image-name.txt"))
		if err != nil {
			return err
		}
		s.ImageName = strings.TrimSpace(string(b))
		if s.ImageName != "Windows.wim" && s.ImageName != "Windows.esd" {
			return errors.New("invalid prepared image")
		}
		if digest, err := hashFile(p.ISOPath); err != nil || digest != p.ISOSHA256 {
			return errors.New("ISO changed during preparation")
		}
		s.ImageSHA256, e = hashFile(filepath.Join(media, "Images", s.ImageName))
		if e != nil {
			return e
		}
		s, e = persistAdvance(journalPath(planPath), s, "prepare.done", FactPlan|FactMedia, h)
		if e != nil {
			return e
		}
		return writeJSONAtomic(filepath.Join(media, "OpenDeploy", "flow-state.json"), s)
	case "install":
		// The pre-reboot handoff committed the installed state. The controller never
		// manufactures an installed receipt just because a subprocess returned zero.
		latest, err := loadFlow(journalPath(planPath))
		if err != nil {
			return err
		}
		if latest.Phase != "installed" {
			return errors.New("OSD returned without installed checkpoint")
		}
		return nil
	case "drivers":
		_, e = persistAdvance(journalPath(planPath), s, "drivers.done", FactPlan|FactBound|FactHandoff|FactHealthy, h)
		return e
	}
	return nil
}
func rootForPlan(stage, root, planPath string) string {
	if stage == "install" {
		return filepath.Dir(planPath)
	}
	return root
}
func checkDeploymentReceipt(root, hash string) error {
	b, e := os.ReadFile(filepath.Join(root, "deployment-complete.json"))
	if e != nil {
		return e
	}
	var r struct{ PlanSHA256 string }
	if e = json.Unmarshal(b, &r); e != nil {
		return e
	}
	if r.PlanSHA256 != hash {
		return errors.New("handoff belongs to another plan")
	}
	return nil
}

// The only installing -> installed checkpoint runs inside OSD before restart.
// Its OS/file facts are explicit external contracts, not axioms about hardware.
func commitConfiguredInstall(planPath, root string) error {
	p, h, s, e := validateConfiguredContext(planPath, "install", root)
	if e != nil {
		return e
	}
	if !isPE() {
		return errors.New("installed checkpoint requires WinPE")
	}
	target, e := resolveDisk(p.Target, listDisks())
	if e != nil {
		return e
	}
	if e = verifyInstalledVolumes(target.Number); e != nil {
		return e
	}
	for _, name := range []string{`C:\Windows\System32\ntoskrnl.exe`, `C:\Windows\Panther\unattend.xml`, `S:\EFI\Microsoft\Boot\BCD`, `S:\EFI\Microsoft\Boot\bootmgfw.efi`} {
		if _, e = os.Stat(name); e != nil {
			return e
		}
	}
	if e = verifyBootstrap(root); e != nil {
		return e
	}
	if e = checkDeploymentReceipt(root, h); e != nil {
		return e
	}
	_, e = persistAdvance(journalPath(planPath), s, "install.done", FactPlan|FactImage|FactBoot|FactHandoff, h)
	return e
}
