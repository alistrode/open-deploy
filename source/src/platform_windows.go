package main

import (
	"encoding/binary"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

var kernel32 = syscall.NewLazyDLL("kernel32.dll")
var deviceIO = kernel32.NewProc("DeviceIoControl")

func isAdministrator() bool {
	r, _, _ := syscall.NewLazyDLL("shell32.dll").NewProc("IsUserAnAdmin").Call()
	return r != 0
}

func queryDevice(path string, code uint32, input []byte, n int) ([]byte, error) {
	p, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return nil, err
	}
	access := uint32(0)
	if code == 0x7405c {
		access = syscall.GENERIC_READ
	}
	h, err := syscall.CreateFile(p, access, 3, nil, syscall.OPEN_EXISTING, 0, 0)
	if err != nil {
		return nil, err
	}
	defer syscall.CloseHandle(h)
	out := make([]byte, n)
	var size uint32
	var in uintptr
	if len(input) > 0 {
		in = uintptr(unsafe.Pointer(&input[0]))
	}
	r, _, er := deviceIO.Call(uintptr(h), uintptr(code), in, uintptr(len(input)), uintptr(unsafe.Pointer(&out[0])), uintptr(n), uintptr(unsafe.Pointer(&size)), 0)
	if r == 0 {
		return nil, er
	}
	return out[:size], nil
}
func readDisk(number int) (Disk, error) {
	if number < 0 || number > 127 {
		return Disk{}, errors.New("invalid disk number")
	}
	path := fmt.Sprintf("\\\\.\\PhysicalDrive%d", number)
	desc, err := queryDevice(path, 0x2d1400, make([]byte, 12), 4096)
	if err != nil {
		return Disk{}, err
	}
	if len(desc) < 36 {
		return Disk{}, errors.New("invalid storage descriptor")
	}
	value := func(off int) string {
		p := int(binary.LittleEndian.Uint32(desc[off : off+4]))
		if p < 36 || p >= len(desc) {
			return ""
		}
		v := desc[p:]
		for i, b := range v {
			if b == 0 {
				v = v[:i]
				break
			}
		}
		return strings.TrimSpace(string(v))
	}
	length, err := queryDevice(path, 0x7405c, nil, 8)
	if err != nil {
		return Disk{}, err
	}
	if len(length) != 8 {
		return Disk{}, errors.New("invalid storage length")
	}
	return Disk{number, strings.TrimSpace(value(12) + " " + value(16)), value(24), binary.LittleEndian.Uint64(length), binary.LittleEndian.Uint32(desc[28:32]) == 7}, nil
}
func listDisks() []Disk {
	out := []Disk{}
	for i := 0; i < 32; i++ {
		d, err := readDisk(i)
		if err == nil {
			out = append(out, d)
		}
	}
	return out
}
func volumeDisk(volume string) int {
	if len(volume) < 2 || volume[1] != ':' {
		return -1
	}
	b, err := queryDevice("\\\\.\\"+volume[:2], 0x2d1080, nil, 12)
	if err != nil || len(b) < 12 {
		return -1
	}
	return int(binary.LittleEndian.Uint32(b[4:8]))
}
func waitDiskVolume(number int) string {
	for n := 0; n < 60; n++ {
		for c := 'D'; c <= 'Z'; c++ {
			v := fmt.Sprintf("%c:", c)
			if volumeDisk(v) == number {
				if _, err := os.Stat(v + "\\ventoy"); err == nil {
					return v
				}
				if _, err := os.Stat(v + "\\"); err == nil {
					label := make([]uint16, 260)
					p, _ := syscall.UTF16PtrFromString(v + "\\")
					r, _, _ := kernel32.NewProc("GetVolumeInformationW").Call(uintptr(unsafe.Pointer(p)), uintptr(unsafe.Pointer(&label[0])), 260, 0, 0, 0, 0, 0)
					if r != 0 && strings.EqualFold(syscall.UTF16ToString(label), "Ventoy") {
						return v
					}
				}
			}
		}
		time.Sleep(time.Second)
	}
	return ""
}
func isPE() bool {
	cmd := exec.Command("reg.exe", "query", "HKLM\\SYSTEM\\CurrentControlSet\\Control\\MiniNT")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return cmd.Run() == nil
}
func liveRunner(action string, args ...string) error {
	if strings.HasPrefix(strings.ToUpper(filepathBase(action)), "SDIO") {
		return runSDIO(action, args...)
	}
	cmd := exec.Command(action, args...)
	cmd.Dir = directoryFor(action)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("%s: %w\n%s", action, err, out)
	}
	return nil
}
func filepathBase(path string) string {
	d := directoryFor(path)
	if d != "" {
		return path[len(d)+1:]
	}
	return path
}

// SDIO declares requireAdministrator even for its non-installing scanner.
// ShellExecute requests the normal Windows elevation prompt; it never clicks or bypasses it.
func runSDIO(action string, args ...string) error {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	_, _, _ = syscall.NewLazyDLL("ole32.dll").NewProc("CoInitializeEx").Call(0, 2)
	defer syscall.NewLazyDLL("ole32.dll").NewProc("CoUninitialize").Call()
	trace := func(s string) {
		f, err := os.OpenFile(filepath.Join(directoryFor(action), "opendeploy-launch.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
		if err == nil {
			fmt.Fprintln(f, time.Now().Format(time.RFC3339), s)
			f.Close()
		}
	}
	trace("launch starting")
	params := []string{}
	for _, a := range args {
		params = append(params, syscall.EscapeArg(a))
	}
	type ShellInfo struct {
		Size                              uint32
		Mask                              uint32
		Window                            uintptr
		Verb, File, Parameters, Directory *uint16
		Show                              int32
		Instance                          uintptr
		IDList                            uintptr
		Class                             *uint16
		ClassKey                          uintptr
		HotKey                            uint32
		Icon                              uintptr
		Process                           syscall.Handle
	}
	verb, _ := syscall.UTF16PtrFromString("runas")
	file, _ := syscall.UTF16PtrFromString(action)
	p, _ := syscall.UTF16PtrFromString(strings.Join(params, " "))
	dir, _ := syscall.UTF16PtrFromString(directoryFor(action))
	s := ShellInfo{Mask: 0x40 | 0x100, Verb: verb, File: file, Parameters: p, Directory: dir, Show: 0}
	s.Size = uint32(unsafe.Sizeof(s))
	r, _, er := syscall.NewLazyDLL("shell32.dll").NewProc("ShellExecuteExW").Call(uintptr(unsafe.Pointer(&s)))
	trace(fmt.Sprintf("ShellExecuteEx returned %d process=%d", r, s.Process))
	if r == 0 {
		return fmt.Errorf("SDIO could not start (elevation may have been declined): %w", er)
	}
	if s.Process == 0 {
		return errors.New("SDIO process handle unavailable")
	}
	defer syscall.CloseHandle(s.Process)
	if _, err := syscall.WaitForSingleObject(s.Process, syscall.INFINITE); err != nil {
		return err
	}
	trace("process wait finished")
	var code uint32
	if err := syscall.GetExitCodeProcess(s.Process, &code); err != nil {
		return err
	}
	if code != 0 {
		return fmt.Errorf("SDIO exit code %d", code)
	}
	return nil
}
func directoryFor(path string) string {
	for i := len(path) - 1; i >= 0; i-- {
		if path[i] == '\\' || path[i] == '/' {
			return path[:i]
		}
	}
	return ""
}
func freeBytes(dir string) (uint64, error) {
	p, _ := syscall.UTF16PtrFromString(filepath.VolumeName(dir) + "\\")
	var available, total, free uint64
	r, _, er := kernel32.NewProc("GetDiskFreeSpaceExW").Call(uintptr(unsafe.Pointer(p)), uintptr(unsafe.Pointer(&available)), uintptr(unsafe.Pointer(&total)), uintptr(unsafe.Pointer(&free)))
	if r == 0 {
		return 0, er
	}
	return available, nil
}

func replaceStateFile(from, to string) error {
	a, e := syscall.UTF16PtrFromString(from)
	if e != nil {
		return e
	}
	b, e := syscall.UTF16PtrFromString(to)
	if e != nil {
		return e
	}
	r, _, err := kernel32.NewProc("MoveFileExW").Call(uintptr(unsafe.Pointer(a)), uintptr(unsafe.Pointer(b)), 9)
	if r == 0 {
		return err
	}
	return nil
}
func machineUUID() (string, error) {
	cmd := exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "$ErrorActionPreference='Stop'; (Get-CimInstance Win32_ComputerSystemProduct).UUID")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	b, e := cmd.Output()
	return strings.TrimSpace(string(b)), e
}
func verifyInstalledVolumes(number int) error {
	script := fmt.Sprintf("$ErrorActionPreference='Stop'; if ((Get-Partition -DriveLetter C).DiskNumber -ne %d -or (Get-Partition -DriveLetter S).DiskNumber -ne %d) { exit 3 }", number, number)
	return exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script).Run()
}
func lockWorkflow(hash string) (func(), error) {
	name, e := syscall.UTF16PtrFromString("Global\\OpenDeploy-Plan-" + hash)
	if e != nil {
		return nil, e
	}
	r, _, err := kernel32.NewProc("CreateMutexW").Call(0, 0, uintptr(unsafe.Pointer(name)))
	if r == 0 {
		return nil, err
	}
	h := syscall.Handle(r)
	wait, e := syscall.WaitForSingleObject(h, 0)
	if e != nil || (wait != 0 && wait != 0x80) {
		syscall.CloseHandle(h)
		return nil, errors.New("configured workflow is already running")
	}
	return func() { kernel32.NewProc("ReleaseMutex").Call(uintptr(h)); syscall.CloseHandle(h) }, nil
}
