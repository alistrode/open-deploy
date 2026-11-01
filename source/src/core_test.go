package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRehearsalCannotReachLiveExecutor(t *testing.T) {
	e := Engine{Options: Options{Root: t.TempDir()}, Runner: func(string, ...string) error { t.Fatal("rehearsal reached a real executor"); return nil }}
	for _, name := range []string{"diskpart.exe", "dism.exe", "bcdboot.exe", "Ventoy2Disk.exe"} {
		if err := e.run("test", name, "must-not-execute"); err != nil {
			t.Fatal(err)
		}
	}
	if len(e.Events) != 4 {
		t.Fatal("missing command evidence")
	}
	for _, v := range e.Events {
		if v.Mode != "REHEARSAL" {
			t.Fatal("bad mode")
		}
	}
}
func TestInstallationRefusesHostWindows(t *testing.T) {
	if isPE() {
		t.Skip("test requires host Windows")
	}
	e := Engine{Options: Options{Live: true}}
	if err := e.Install(); err == nil || !strings.Contains(err.Error(), "WinPE") {
		t.Fatal("host installation was not blocked", err)
	}
}
func TestInvalidAndWrongTypeDisks(t *testing.T) {
	e := Engine{}
	for _, d := range []Disk{{-1, "x", "x", 128 << 30, true}, {1, "x", "", 128 << 30, true}, {1, "x", "x", 1 << 30, true}, {1, "x", "x", 128 << 30, false}} {
		if err := e.validateDisk(d, true); err == nil {
			t.Fatal("invalid USB accepted", d)
		}
	}
	if err := e.validateDisk(Disk{2, "x", "x", 128 << 30, true}, false); err == nil {
		t.Fatal("installation onto USB accepted")
	}
}
func TestBundleContainsRealOSDHookAndDedicatedPE(t *testing.T) {
	root := t.TempDir()
	testDriverPayload(t, root)
	for _, name := range []string{"scripts/Install-Handoff.ps1", "scripts/Build-WinPE.ps1", "scripts/Start-WinPE.ps1", "scripts/Install-Drivers.ps1", "vendor/sdio/SDIO_x64_R887.exe", "upstream/OSD/OSD.psd1", "osd/patched/OSDCloud.ps1", "osd/patched/Start-OSDCloud.ps1", "dependencies.lock.json", "THIRD_PARTY.md"} {
		p := filepath.Join(root, filepath.FromSlash(name))
		os.MkdirAll(filepath.Dir(p), 0755)
		os.WriteFile(p, []byte("fixture:"+name), 0644)
	}
	if err := buildBundle(Options{Root: root}); err != nil {
		t.Fatal(err)
	}
	patched, err := os.ReadFile(filepath.Join(root, "bundle", "OpenDeploy", "upstream", "OSD", "Public", "OSDCloud.ps1"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(patched), "osd/patched/OSDCloud.ps1") {
		t.Fatal("patch not placed in imported OSD module")
	}
	raw, err := os.ReadFile(filepath.Join(root, "bundle", "ventoy", "ventoy.json"))
	if err != nil {
		t.Fatal(err)
	}
	var cfg map[string]any
	if err = json.Unmarshal(raw, &cfg); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), "injection") || !strings.Contains(string(raw), "OpenDeployPE.iso") {
		t.Fatal("bundle assumes stock ISO PE")
	}
	if err = verifyBootstrap(filepath.Join(root, "bundle", "OpenDeploy")); err != nil {
		t.Fatal(err)
	}
}
func TestImageIndexRejectedBeforeCommands(t *testing.T) {
	e := Engine{Options: Options{Root: t.TempDir(), Target: Disk{31, "test", "test", 256 << 30, false}, Index: 0}, Runner: func(string, ...string) error { t.Fatal("invalid index reached execution"); return nil }}
	if err := e.Install(); err == nil {
		t.Fatal("invalid image index accepted")
	}
	if len(e.Events) != 0 {
		t.Fatal("commands planned with invalid image index")
	}
}
func TestRehearsalUsesSameOwnerAsLive(t *testing.T) {
	e := Engine{Options: Options{Root: t.TempDir(), Target: Disk{31, "test", "test", 256 << 30, false}, Index: 1}}
	if err := e.Install(); err != nil {
		t.Fatal(err)
	}
	if len(e.Events) != 1 || e.Events[0].Action != "OSD rehearsal" {
		t.Fatal("rehearsal described a different owner", e.Events)
	}
}
