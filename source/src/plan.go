package main

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type DiskIdentity struct {
	Serial string `json:"serial"`
	Size   uint64 `json:"size"`
	USB    bool   `json:"usb"`
}
type ExecutionPlan struct {
	Schema        int          `json:"schema"`
	ID            string       `json:"id"`
	MachineUUID   string       `json:"machine_uuid"`
	ISOPath       string       `json:"iso_path"`
	ISOSHA256     string       `json:"iso_sha256"`
	ImageIndex    int          `json:"image_index"`
	USB           DiskIdentity `json:"usb"`
	Target        DiskIdentity `json:"target"`
	DriversSHA256 string       `json:"drivers_sha256"`
	EraseUSB      bool         `json:"erase_usb"`
	EraseTarget   bool         `json:"erase_target"`
}

func validUUID(s string) bool {
	v := strings.ReplaceAll(strings.ToLower(s), "-", "")
	b, e := hex.DecodeString(v)
	return e == nil && len(b) == 16 && len(s) == 36 && s[8] == '-' && s[13] == '-' && s[18] == '-' && s[23] == '-' && v != strings.Repeat("0", 32) && v != strings.Repeat("f", 32)
}
func (p ExecutionPlan) Validate() error {
	if p.Schema != 1 || !validUUID(p.ID) || !validUUID(p.MachineUUID) {
		return errors.New("schema and actual plan/machine UUID required")
	}
	if !validHash(p.ISOSHA256) || !validHash(p.DriversSHA256) || !filepath.IsAbs(p.ISOPath) || p.ImageIndex < 1 || p.ImageIndex > 99 {
		return errors.New("absolute ISO path, SHA256s and image index required")
	}
	if !p.EraseUSB || !p.EraseTarget {
		return errors.New("preconfiguration must explicitly approve the exact USB and target erasure")
	}
	if !p.USB.USB || p.Target.USB || p.USB.Size < 16<<30 || p.Target.Size < 64<<30 {
		return errors.New("invalid disk class or size")
	}
	for _, d := range []DiskIdentity{p.USB, p.Target} {
		if strings.TrimSpace(d.Serial) == "" || d.Serial != strings.TrimSpace(d.Serial) || strings.Contains(strings.ToUpper(d.Serial), "REPLACE") {
			return errors.New("actual disk serial required")
		}
	}
	if p.USB.Serial == p.Target.Serial {
		return errors.New("USB and target must have distinct serials")
	}
	return nil
}
func loadPlan(path string) (ExecutionPlan, string, error) {
	var p ExecutionPlan
	b, e := os.ReadFile(path)
	if e != nil {
		return p, "", e
	}
	if e = strictJSON(b, &p); e != nil {
		return p, "", e
	}
	if e = p.Validate(); e != nil {
		return p, "", e
	}
	if !bytes.Equal(b, canonicalJSON(p)) {
		return p, "", errors.New("plan is not sealed canonical JSON; use --configure")
	}
	h, e := hashFile(path)
	return p, h, e
}
func resolveDisk(id DiskIdentity, disks []Disk) (Disk, error) {
	var matches []Disk
	for _, d := range disks {
		if d.Serial == id.Serial && d.Size == id.Size && d.USB == id.USB {
			matches = append(matches, d)
		}
	}
	if len(matches) != 1 {
		return Disk{}, fmt.Errorf("expected exactly one disk matching serial/size/type, got %d", len(matches))
	}
	return matches[0], nil
}
func configurePlan(specPath, planPath, root string) error {
	return configureWithInventory(specPath, planPath, root, listDisks())
}
func configureWithInventory(specPath, planPath, root string, inventory []Disk) error {
	var p ExecutionPlan
	b, e := os.ReadFile(specPath)
	if e != nil {
		return e
	}
	if e = strictJSON(b, &p); e != nil {
		return e
	}
	if p.ID == "" {
		var b [16]byte
		if _, e = rand.Read(b[:]); e != nil {
			return e
		}
		p.ID = fmt.Sprintf("%x-%x-%x-%x-%x", b[:4], b[4:6], b[6:8], b[8:10], b[10:])
	}
	if e = p.Validate(); e != nil {
		return e
	}
	if _, e = resolveDisk(p.USB, inventory); e != nil {
		return e
	}
	if h, e := hashFile(p.ISOPath); e != nil || h != p.ISOSHA256 {
		return errors.New("ISO differs from approved configuration")
	}
	if h, e := hashFile(filepath.Join(root, "drivers-manifest.json")); e != nil || h != p.DriversSHA256 {
		return errors.New("driver manifest differs from approved configuration")
	}
	if _, err := os.Stat(journalPath(planPath)); err == nil {
		old, err := loadFlow(journalPath(planPath))
		if err != nil || old.Phase != "configured" {
			return errors.New("existing operation progressed or journal is corrupt; use a separate runtime folder")
		}
	} else if !os.IsNotExist(err) {
		return err
	}
	if e = writeJSONAtomic(planPath, p); e != nil {
		return e
	}
	_, h, e := loadPlan(planPath)
	if e != nil {
		return e
	}
	return writeJSONAtomic(journalPath(planPath), FlowState{Schema: 1, PlanSHA256: h, Phase: "configured"})
}
