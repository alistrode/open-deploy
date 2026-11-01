package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

var ErrStagePending = errors.New("stage pending restart")

type Disk struct {
	Number        int
	Model, Serial string
	Size          uint64
	USB           bool
}
type Options struct {
	Root, ISO           string
	PlanFile, MediaRoot string
	Resume              bool
	USB, Target         Disk
	Index               int
	Live                bool
	Stage               string
	Consent             bool
}
type Event struct {
	Stage, Action, Mode string
	Args                []string
	Time                string
}
type Engine struct {
	Options Options
	Events  []Event
	Output  func(string)
	Runner  func(string, ...string) error
}

func (e *Engine) log(s string) {
	if e.Output != nil {
		e.Output(s)
	}
}
func (e *Engine) run(stage, action string, args ...string) error {
	mode := "REHEARSAL"
	if e.Options.Live {
		mode = "LIVE"
	}
	e.Events = append(e.Events, Event{stage, action, mode, args, time.Now().Format(time.RFC3339)})
	e.log("[" + mode + "] " + action + " " + strings.Join(args, " "))
	if !e.Options.Live {
		return nil
	}
	if e.Runner == nil {
		return errors.New("no live executor configured")
	}
	return e.Runner(action, args...)
}
func (e *Engine) save() error {
	dir := filepath.Join(e.Options.Root, "evidence")
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}
	data, _ := json.MarshalIndent(e.Events, "", "  ")
	return os.WriteFile(filepath.Join(dir, "flow-events.json"), data, 0644)
}
func (e *Engine) validateDisk(d Disk, usb bool) error {
	if d.Number < 0 || d.Size < 16*1024*1024*1024 || d.Serial == "" {
		return errors.New("target disk identity is incomplete")
	}
	if d.USB != usb {
		return errors.New("disk type does not match this operation")
	}
	if !usb && d.Size < 64*1024*1024*1024 {
		return errors.New("system disk must be at least 64 GiB")
	}
	if e.Options.Live {
		if !e.Options.Consent {
			return errors.New("select a disk and acknowledge erasing it first")
		}
		actual, err := readDisk(d.Number)
		if err != nil {
			return err
		}
		if actual.Serial != d.Serial || actual.Size != d.Size || actual.USB != d.USB {
			return errors.New("disk identity changed; operation stopped")
		}
		if !isPE() && d.Number == volumeDisk(os.Getenv("SystemDrive")) {
			return errors.New("refusing the running system disk")
		}
	}
	return nil
}
func (e *Engine) Prepare() error {
	if e.Options.Live && (e.Options.Stage != "prepare" || isPE()) {
		return errors.New("USB preparation only allowed in the host prepare stage")
	}
	if err := e.validateDisk(e.Options.USB, true); err != nil {
		return err
	}
	if e.Options.Live {
		if !strings.EqualFold(filepath.Ext(e.Options.ISO), ".iso") {
			return errors.New("select your Windows ISO")
		}
		if _, err := os.Stat(e.Options.ISO); err != nil {
			return err
		}
		if volumeDisk(filepath.VolumeName(e.Options.ISO)) == e.Options.USB.Number {
			return errors.New("ISO is on the USB disk that would be formatted")
		}
		if volumeDisk(filepath.VolumeName(e.Options.Root)) == e.Options.USB.Number {
			return errors.New("program is running from the USB disk that would be formatted")
		}
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Hour)
		defer cancel()
		if err := fetchBootstrap(ctx, e.Options.Root, e.Output); err != nil {
			return err
		}
		if err := extractStorage(e.Options.Root); err != nil {
			return err
		}
	}
	if err := buildBundle(e.Options); err != nil {
		return err
	}
	if e.Options.Live {
		if err := e.run("prepare", "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", filepath.Join(e.Options.Root, "scripts", "Build-WinPE.ps1"), "-Root", e.Options.Root, "-Bundle", filepath.Join(e.Options.Root, "bundle"), "-SourceISO", e.Options.ISO); err != nil {
			return err
		}
		needed := uint64(1024 * 1024 * 1024)
		err := filepath.Walk(filepath.Join(e.Options.Root, "bundle"), func(_ string, info os.FileInfo, err error) error {
			if err != nil {
				return err
			}
			if !info.IsDir() {
				needed += uint64(info.Size())
			}
			return nil
		})
		if err != nil {
			return err
		}
		if needed > e.Options.USB.Size {
			return fmt.Errorf("USB is too small: payload and reserve require %.2f GiB", float64(needed)/(1<<30))
		}
		if err = e.validateDisk(e.Options.USB, true); err != nil {
			return err
		}
	}
	ventoy, err := findFile(filepath.Join(e.Options.Root, "vendor", "ventoy"), "Ventoy2Disk.exe")
	if err != nil {
		return err
	}
	if e.Options.Live {
		if err = os.Remove(filepath.Join(filepath.Dir(ventoy), "cli_done.txt")); err != nil && !os.IsNotExist(err) {
			return err
		}
	}
	if err = e.run("prepare", ventoy, "VTOYCLI", "/I", "/PhyDrive:"+strconv.Itoa(e.Options.USB.Number), "/GPT", "/FS:EXFAT"); err != nil {
		return err
	}
	if e.Options.Live {
		// The CLI's completion marker, rather than exit code alone, is authoritative.
		done := filepath.Join(filepath.Dir(ventoy), "cli_done.txt")
		ok := false
		for n := 0; n < 180; n++ {
			b, er := os.ReadFile(done)
			if er == nil {
				if strings.TrimSpace(string(b)) != "0" {
					return errors.New("Ventoy reported failure")
				}
				ok = true
				break
			}
			time.Sleep(time.Second)
		}
		if !ok {
			return errors.New("Ventoy completion marker not found")
		}
		drive := waitDiskVolume(e.Options.USB.Number)
		if drive == "" {
			return errors.New("cannot locate the prepared USB volume")
		}
		if volumeDisk(drive) != e.Options.USB.Number {
			return errors.New("USB volume identity mismatch")
		}
		e.Options.MediaRoot = drive + "\\"
		if err = copyTree(filepath.Join(e.Options.Root, "bundle"), drive+"\\"); err != nil {
			return err
		}

	}
	e.log("启动介质步骤已完成；预演不会格式化或复制你的ISO。")
	return e.save()
}

// Installation is delegated to one OSD task chain. Handoff is an explicit
// pre-reboot hook in that SAME chain; there is no parallel legacy write path.
func (e *Engine) Install() error {
	if e.Options.Live && (!isPE() || e.Options.Stage != "install") {
		return errors.New("system installation is only allowed from the WinPE install stage")
	}
	if err := e.validateDisk(e.Options.Target, false); err != nil {
		return err
	}
	if e.Options.Index < 1 || e.Options.Index > 99 {
		return errors.New("invalid image index")
	}
	if !e.Options.Live {
		return e.run("install", "OSD rehearsal", "partition, apply image, offline drivers, handoff, boot, restart")
	}
	// WinPE reads the image extracted by the host, so PE never needs to mount an ISO.
	media := filepath.Dir(filepath.Dir(e.Options.PlanFile)) + string(os.PathSeparator)
	if e.Options.PlanFile == "" {
		return errors.New("sealed plan required")
	}
	if volumeDisk(filepath.VolumeName(media)) == e.Options.Target.Number {
		return errors.New("target is the installation USB")
	}
	b, err := os.ReadFile(filepath.Join(media, "OpenDeploy", "image-name.txt"))
	if err != nil {
		return err
	}
	name := strings.TrimSpace(string(b))
	if name != "Windows.wim" && name != "Windows.esd" {
		return errors.New("invalid prepared image name")
	}
	image := filepath.Join(media, "Images", name)
	if _, err = os.Stat(image); err != nil {
		return err
	}
	runtimeRoot := filepath.Join(media, "OpenDeploy")
	if err = verifyBootstrap(runtimeRoot); err != nil {
		return err
	}
	if err = e.run("preflight", "dism.exe", "/Get-WimInfo", "/WimFile:"+image, "/Index:"+strconv.Itoa(e.Options.Index)); err != nil {
		return err
	}
	// Recheck disk immediately before giving the write owner the confirmed identity.
	if err = e.validateDisk(e.Options.Target, false); err != nil {
		return err
	}
	return e.run("install", "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", filepath.Join(runtimeRoot, "osd", "OpenDeploy-OSD.ps1"), "-DiskNumber", strconv.Itoa(e.Options.Target.Number), "-DiskSerial", e.Options.Target.Serial, "-DiskSize", strconv.FormatUint(e.Options.Target.Size, 10), "-ImageFile", image, "-ImageIndex", strconv.Itoa(e.Options.Index), "-RuntimeRoot", runtimeRoot)
}

// Third click starts a resumable driver worker; subsequent boots resume that
// worker automatically. Merely opening the stage UI never silently installs.
func (e *Engine) Drivers() error {
	if e.Options.Live && (isPE() || e.Options.Stage != "drivers") {
		return errors.New("drivers require the installed Windows stage")
	}
	if !e.Options.Live {
		return e.run("drivers", "driver rehearsal", "verify payload, PnP matching, SDIO online missing, reboot/resume, health check")
	}
	if _, err := os.Stat(filepath.Join(e.Options.Root, "deployment-complete.json")); err != nil {
		return errors.New("missing verified OpenDeploy deployment handoff")
	}
	if err := verifyBootstrap(e.Options.Root); err != nil {
		return err
	}
	args := []string{"-NoProfile", "-ExecutionPolicy", "Bypass", "-File", filepath.Join(e.Options.Root, "scripts", "Install-Drivers.ps1"), "-Root", e.Options.Root}
	if e.Options.Resume {
		args = append(args, "-Resume")
	}
	if err := e.run("drivers", "powershell.exe", args...); err != nil {
		return err
	}
	if b, err := os.ReadFile(filepath.Join(e.Options.Root, "drivers-complete.json")); err == nil {
		var marker struct{ PlanSHA256 string }
		_, hash, loadErr := loadPlan(e.Options.PlanFile)
		if json.Unmarshal(b, &marker) == nil && loadErr == nil && marker.PlanSHA256 == hash {
			return nil
		}
	}
	b, err := os.ReadFile(filepath.Join(e.Options.Root, "driver-state.json"))
	if err == nil {
		var state struct{ Status string }
		if json.Unmarshal(b, &state) == nil && (state.Status == "reboot-pending" || state.Status == "installing") {
			return ErrStagePending
		}
	}
	return errors.New("driver worker exited without completion proof")
}

func buildBundle(o Options) error {
	out := filepath.Join(o.Root, "bundle")
	if err := os.RemoveAll(out); err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Join(out, "ISO"), 0755); err != nil {
		return err
	}
	// A dedicated ADK PE is built before the USB is erased. A stock installer PE
	// cannot be assumed to contain PowerShell, WMI and the Storage cmdlets.
	cfg := map[string]any{"control": []map[string]string{{"VTOY_DEFAULT_SEARCH_ROOT": "/ISO"}, {"VTOY_DEFAULT_IMAGE": "/ISO/OpenDeployPE.iso"}, {"VTOY_MENU_TIMEOUT": "5"}}}
	b, _ := json.MarshalIndent(cfg, "", "  ")
	if err := os.MkdirAll(filepath.Join(out, "ventoy"), 0755); err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(out, "ventoy", "ventoy.json"), b, 0644); err != nil {
		return err
	}
	dest := filepath.Join(out, "OpenDeploy")
	for _, dir := range []string{"bootstrap-drivers", "scripts", "vendor/sdio", "osd", "upstream/OSD"} {
		if err := copyTree(filepath.Join(o.Root, filepath.FromSlash(dir)), filepath.Join(dest, filepath.FromSlash(dir))); err != nil {
			return err
		}
	}
	for _, name := range []string{"drivers-manifest.json", "dependencies.lock.json", "THIRD_PARTY.md"} {
		if err := copyFile(filepath.Join(o.Root, name), filepath.Join(dest, name)); err != nil {
			return err
		}
	}
	if err := copyFile(filepath.Join(o.Root, "osd", "patched", "OSDCloud.ps1"), filepath.Join(dest, "upstream", "OSD", "Public", "OSDCloud.ps1")); err != nil {
		return err
	}
	if err := copyFile(filepath.Join(o.Root, "osd", "patched", "Start-OSDCloud.ps1"), filepath.Join(dest, "upstream", "OSD", "Public", "Start-OSDCloud.ps1")); err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(dest, "unattend.xml"), []byte(unattendXML), 0644); err != nil {
		return err
	}
	if o.PlanFile != "" {
		for _, name := range []string{"1-Prepare.cmd", "2-Install.cmd", "3-Drivers.cmd"} {
			if err := copyFile(filepath.Join(o.Root, name), filepath.Join(dest, name)); err != nil {
				return err
			}
		}
	}
	if o.PlanFile != "" {
		for _, name := range []string{"plan.json", "flow-state.json"} {
			from := filepath.Join(filepath.Dir(o.PlanFile), name)
			if name == "plan.json" {
				from = o.PlanFile
			}
			if err := copyFile(from, filepath.Join(dest, name)); err != nil {
				return err
			}
		}
	}
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	return copyFile(exe, filepath.Join(dest, "OpenDeploy.exe"))
}

func copyFile(from, to string) error {
	if err := os.MkdirAll(filepath.Dir(to), 0755); err != nil {
		return err
	}
	a, err := os.Open(from)
	if err != nil {
		return err
	}
	defer a.Close()
	b, err := os.Create(to)
	if err != nil {
		return err
	}
	_, err = io.Copy(b, a)
	ce := b.Close()
	if err != nil {
		return err
	}
	return ce
}
func copyTree(from, to string) error {
	return filepath.Walk(from, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(from, path)
		if err != nil {
			return err
		}
		dst := filepath.Join(to, rel)
		if info.IsDir() {
			return os.MkdirAll(dst, 0755)
		}
		return copyFile(path, dst)
	})
}
func findFile(root, name string) (string, error) {
	found := ""
	err := filepath.Walk(root, func(p string, i os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !i.IsDir() && strings.EqualFold(i.Name(), name) {
			found = p
		}
		return nil
	})
	if err != nil {
		return "", err
	}
	if found == "" {
		return "", fmt.Errorf("missing dependency: %s", name)
	}
	return found, nil
}

const unattendXML = `<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
 <settings pass="specialize"><component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS"><ComputerName>*</ComputerName><TimeZone>China Standard Time</TimeZone></component></settings>
 <settings pass="oobeSystem"><component name="Microsoft-Windows-International-Core" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS"><InputLocale>__IMAGE_LANGUAGE__</InputLocale><SystemLocale>__IMAGE_LANGUAGE__</SystemLocale><UILanguage>__IMAGE_LANGUAGE__</UILanguage><UserLocale>__IMAGE_LANGUAGE__</UserLocale></component><component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS"><AutoLogon><Password><Value></Value><PlainText>true</PlainText></Password><Enabled>true</Enabled><LogonCount>1</LogonCount><Username>User</Username></AutoLogon><OOBE><HideEULAPage>true</HideEULAPage><HideOnlineAccountScreens>true</HideOnlineAccountScreens><HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE><ProtectYourPC>1</ProtectYourPC></OOBE><UserAccounts><LocalAccounts><LocalAccount xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" wcm:action="add"><Name>User</Name><DisplayName>User</DisplayName><Group>Administrators</Group><Password><Value></Value><PlainText>true</PlainText></Password></LocalAccount></LocalAccounts></UserAccounts></component></settings>
</unattend>`
