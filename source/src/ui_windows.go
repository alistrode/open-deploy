package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

var user32 = syscall.NewLazyDLL("user32.dll")
var gdi32 = syscall.NewLazyDLL("gdi32.dll")
var createWindow = user32.NewProc("CreateWindowExW")
var sendMessage = user32.NewProc("SendMessageW")
var postMessage = user32.NewProc("PostMessageW")
var mainH, isoEdit, indexEdit, usbCombo, targetCombo, consentBox, logBox, statusLabel uintptr
var font uintptr
var buttons [3]uintptr
var usbDisks, targetDisks []Disk
var uiEngine *Engine
var uiQueue []string
var queueMu sync.Mutex
var busy bool

type WndClass struct {
	Size, Style                        uint32
	Proc                               uintptr
	ClsExtra, WndExtra                 int32
	Instance, Icon, Cursor, Background uintptr
	MenuName, ClassName                *uint16
	IconSmall                          uintptr
}
type Message struct {
	Hwnd           uintptr
	Message        uint32
	Wparam, Lparam uintptr
	Time           uint32
	X, Y           int32
	Private        uint32
}

func ptr(s string) uintptr { p, _ := syscall.UTF16PtrFromString(s); return uintptr(unsafe.Pointer(p)) }
func control(kind, text string, style uint32, x, y, w, h, id int) uintptr {
	r, _, _ := createWindow.Call(0, ptr(kind), ptr(text), uintptr(style|0x50000000), uintptr(x), uintptr(y), uintptr(w), uintptr(h), mainH, uintptr(id), 0, 0)
	sendMessage.Call(r, 0x30, font, 1)
	return r
}
func text(h uintptr) string {
	n, _, _ := user32.NewProc("GetWindowTextLengthW").Call(h)
	b := make([]uint16, n+1)
	user32.NewProc("GetWindowTextW").Call(h, uintptr(unsafe.Pointer(&b[0])), n+1)
	return syscall.UTF16ToString(b)
}
func setText(h uintptr, s string) { user32.NewProc("SetWindowTextW").Call(h, ptr(s)) }
func enqueue(s string) {
	queueMu.Lock()
	uiQueue = append(uiQueue, s)
	queueMu.Unlock()
	postMessage.Call(mainH, 0x8001, 0, 0)
}
func addLine(s string) {
	sendMessage.Call(logBox, 0x180, 0, ptr(s))
	n, _, _ := sendMessage.Call(logBox, 0x18b, 0, 0)
	if n > 0 {
		sendMessage.Call(logBox, 0x197, n-1, 0)
	}
}
func wndProc(hwnd uintptr, msg uint32, wp, lp uintptr) uintptr {
	switch msg {
	case 0x111:
		id := int(wp & 0xffff)
		if id >= 101 && id <= 103 && !busy {
			startStage(id - 101)
		}
	case 0x8001:
		queueMu.Lock()
		q := uiQueue
		uiQueue = nil
		queueMu.Unlock()
		for _, s := range q {
			addLine(s)
		}
		return 0
	case 0x8002:
		busy = false
		for i, b := range buttons {
			enabled := uintptr(0)
			if stageAllowed(uiEngine.Options, i) {
				enabled = 1
			}
			user32.NewProc("EnableWindow").Call(b, enabled)
		}
		return 0
	case 0x10:
		user32.NewProc("DestroyWindow").Call(hwnd)
		return 0
	case 0x2:
		user32.NewProc("PostQuitMessage").Call(0)
		return 0
	}
	r, _, _ := user32.NewProc("DefWindowProcW").Call(hwnd, uintptr(msg), wp, lp)
	return r
}
func selected(h uintptr, disks []Disk) (Disk, error) {
	n, _, _ := sendMessage.Call(h, 0x147, 0, 0)
	if int32(n) < 0 || int(n) >= len(disks) {
		return Disk{}, fmt.Errorf("请先选择目标磁盘")
	}
	return disks[n], nil
}
func startStage(i int) {
	o := uiEngine.Options
	if !stageAllowed(o, i) {
		addLine("当前运行阶段不允许此操作")
		return
	}
	o.ISO = strings.TrimSpace(text(isoEdit))
	index, err := strconv.Atoi(text(indexEdit))
	if err != nil {
		addLine("映像索引需要是数字")
		return
	}
	o.Index = index
	if i == 0 {
		o.USB, err = selected(usbCombo, usbDisks)
	}
	if i == 1 {
		o.Target, err = selected(targetCombo, targetDisks)
	}
	if err != nil {
		addLine(err.Error())
		return
	}
	checked, _, _ := sendMessage.Call(consentBox, 0xf0, 0, 0)
	o.Consent = checked == 1
	uiEngine.Options = o
	busy = true
	for _, b := range buttons {
		user32.NewProc("EnableWindow").Call(b, 0)
	}
	go func() {
		var er error
		switch i {
		case 0:
			er = uiEngine.Prepare()
		case 1:
			er = uiEngine.Install()
		case 2:
			er = uiEngine.Drivers()
		}
		if errors.Is(er, ErrStagePending) {
			enqueue("驱动阶段等待重启，将自动继续；尚未标记完成。")
		} else if er != nil {
			enqueue("未通过：" + er.Error())
		} else {
			enqueue(fmt.Sprintf("第%d步已通过%s", i+1, map[bool]string{false: "预演检查（未装机）", true: "执行检查"}[o.Live]))
		}
		postMessage.Call(mainH, 0x8002, 0, 0)
	}()
}
func main() {
	runtime.LockOSThread()
	live := flag.Bool("live", true, "execute the sealed preapproved operation")
	rehearsal := flag.Bool("rehearsal", false, "read-only rehearsal")
	stage := flag.String("stage", "prepare", "prepare/install/drivers")
	cliTest := flag.Bool("self-test", false, "run the non-destructive flow tests")
	fetch := flag.Bool("fetch-bootstrap", false, "download community network/storage packages without installing them")
	run := flag.Bool("run", false, "execute a sealed preconfigured stage without GUI")
	plan := flag.String("plan", "", "sealed plan JSON")
	inventory := flag.Bool("inventory", false, "read-only machine/disk inventory for AI preconfiguration")
	configure := flag.String("configure", "", "seal an AI-prepared specification after input checks")
	resume := flag.Bool("resume", false, "resume an already activated driver stage after reboot")
	checkpoint := flag.String("checkpoint", "", "internal pre-reboot installed checkpoint")
	validatePlan := flag.Bool("validate-plan", false, "validate sealed plan and print its digest")
	flag.Parse()
	liveExplicit := false
	flag.Visit(func(f *flag.Flag) {
		if f.Name == "live" {
			liveExplicit = true
		}
	})
	if !liveExplicit && (*rehearsal || *cliTest || *fetch) {
		*live = false
	}
	exe, _ := os.Executable()
	root := filepath.Dir(exe)
	if *plan == "" {
		*plan = filepath.Join(root, "plan.json")
	}
	if *live && !*inventory && *configure == "" && !*validatePlan && *checkpoint == "" {
		*run = true
	}
	if err := validateLaunch(*live, *rehearsal, *cliTest, *fetch, *stage); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	if *live && !isPE() && !isAdministrator() {
		if err := runSDIO(exe, os.Args[1:]...); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}
	if *inventory || *configure != "" || *validatePlan || *checkpoint != "" || *run {
		var err error
		switch {
		case *inventory:
			var uuid string
			uuid, err = machineUUID()
			if err == nil {
				payload := struct {
					MachineUUID string `json:"machine_uuid"`
					Disks       []Disk `json:"disks"`
				}{uuid, listDisks()}
				err = json.NewEncoder(os.Stdout).Encode(payload)
			}
		case *configure != "":
			err = configurePlan(*configure, *plan, root)
		case *validatePlan:
			var hash string
			_, hash, err = loadPlan(*plan)
			if err == nil && *stage != "prepare" {
				_, _, _, err = validateConfiguredContext(*plan, *stage, filepath.Dir(*plan))
			}
			if err == nil {
				fmt.Println(hash)
			}
		case *checkpoint != "":
			if *checkpoint != "installed" {
				err = errors.New("unsupported checkpoint")
			} else {
				err = commitConfiguredInstall(*plan, root)
			}
		case *run:
			if !*live {
				err = errors.New("--run requires actual execution; use isolated model/simulation checks for rehearsal")
			} else {
				err = runConfiguredStage(*plan, *stage, root, *resume)
			}
		}
		if errors.Is(err, ErrStagePending) {
			fmt.Println("Stage is pending reboot; it will resume automatically.")
			return
		}
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}
	if *stage == "drivers" {
		if _, err := os.Stat(filepath.Join(root, "drivers-complete.json")); err == nil {
			return
		}
	}
	uiEngine = &Engine{Options: Options{Root: root, Index: 1, Live: *live, Stage: *stage}, Output: enqueue, Runner: liveRunner}
	if *fetch {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Hour)
		defer cancel()
		if err := fetchBootstrap(ctx, root, func(s string) { fmt.Println(s) }); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}
	if *cliTest {
		uiEngine.Output = func(s string) { fmt.Println(s) }
		uiEngine.Options.USB = Disk{30, "TEST-USB", "SIMULATED-USB", 128 << 30, true}
		uiEngine.Options.Target = Disk{31, "TEST-SSD", "SIMULATED-SSD", 256 << 30, false}
		for _, f := range []func() error{uiEngine.Prepare, uiEngine.Install, uiEngine.Drivers} {
			if err := f(); err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
		}
		return
	}
	cls := syscall.StringToUTF16Ptr("OpenDeployNative")
	instance, _, _ := kernel32.NewProc("GetModuleHandleW").Call(0)
	cursor, _, _ := user32.NewProc("LoadCursorW").Call(0, 32512)
	wc := WndClass{Size: uint32(unsafe.Sizeof(WndClass{})), Proc: syscall.NewCallback(wndProc), Instance: instance, Cursor: cursor, Background: 6, ClassName: cls}
	user32.NewProc("RegisterClassExW").Call(uintptr(unsafe.Pointer(&wc)))
	mainH, _, _ = createWindow.Call(0, uintptr(unsafe.Pointer(cls)), ptr("OpenDeploy · 开源三步装机"), 0x00ca0000, 100, 70, 1000, 730, 0, 0, instance, 0)
	font, _, _ = gdi32.NewProc("CreateFontW").Call(19, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, ptr("Microsoft YaHei UI"))
	control("STATIC", "OpenDeploy   开源三步装机", 0, 28, 20, 900, 36, 0)
	mode := "当前：安全预演｜不格式化、不装系统、不装驱动"
	if *live {
		mode = "当前：实际执行｜目标磁盘与清除确认必须由你选择"
	}
	control("STATIC", mode, 0, 28, 60, 900, 30, 0)
	control("STATIC", "你的Windows ISO", 0, 28, 104, 170, 25, 0)
	isoEdit = control("EDIT", "", 0x00800000|0x80, 202, 101, 730, 30, 201)
	control("STATIC", "启动U盘", 0, 28, 148, 170, 25, 0)
	usbCombo = control("COMBOBOX", "", 0x00200000|3, 202, 143, 730, 220, 202)
	control("STATIC", "安装目标磁盘", 0, 28, 192, 170, 25, 0)
	targetCombo = control("COMBOBOX", "", 0x00200000|3, 202, 187, 730, 220, 203)
	control("STATIC", "映像索引", 0, 28, 235, 170, 25, 0)
	indexEdit = control("EDIT", "1", 0x00800000, 202, 232, 70, 30, 204)
	consentBox = control("BUTTON", "我确认实际执行时会清空所选磁盘（预演无需勾选）", 3, 295, 230, 640, 30, 205)
	for i, t := range []string{"1  一键准备启动介质", "2  一键安装系统", "3  一键安装社区驱动"} {
		buttons[i] = control("BUTTON", t, 0, 28+i*309, 290, 292, 53, 101+i)
	}
	control("STATIC", "每段仅一个开始按钮；驱动需要重启时自动恢复，并核对设备状态。", 0, 28, 357, 920, 26, 0)
	control("STATIC", "实际流程：选好ISO/U盘 → 准备 → 从U盘启动后确认目标盘 → 新系统装驱动。", 0, 28, 388, 920, 26, 0)
	logBox = control("LISTBOX", "", 0x00800000|0x00200000|0x100|1, 28, 430, 914, 218, 206)
	if *live {
		for _, d := range listDisks() {
			label := fmt.Sprintf("磁盘%d · %s · %d GiB · %s", d.Number, d.Model, d.Size>>30, d.Serial)
			if d.USB {
				usbDisks = append(usbDisks, d)
				sendMessage.Call(usbCombo, 0x143, 0, ptr(label))
			} else {
				targetDisks = append(targetDisks, d)
				sendMessage.Call(targetCombo, 0x143, 0, ptr(label))
			}
		}
	} else {
		usbDisks = []Disk{{30, "模拟U盘", "SIMULATED-USB", 128 << 30, true}}
		targetDisks = []Disk{{31, "模拟SSD", "SIMULATED-SSD", 256 << 30, false}}
		sendMessage.Call(usbCombo, 0x143, 0, ptr("模拟U盘 · 128 GiB（不会访问真实磁盘）"))
		sendMessage.Call(targetCombo, 0x143, 0, ptr("模拟SSD · 256 GiB（不会访问真实磁盘）"))
	}
	sendMessage.Call(usbCombo, 0x14e, 0, 0)
	if *live {
		sendMessage.Call(targetCombo, 0x14e, ^uintptr(0), 0)
	} else {
		sendMessage.Call(targetCombo, 0x14e, 0, 0)
	}
	if *live {
		// Configuration belongs to the stage that actually consumes it. Do not
		// offer an edition/target selection on the host and silently lose it at boot.
		switch *stage {
		case "prepare":
			user32.NewProc("EnableWindow").Call(targetCombo, 0)
			user32.NewProc("EnableWindow").Call(indexEdit, 0)
		case "install":
			user32.NewProc("EnableWindow").Call(isoEdit, 0)
			user32.NewProc("EnableWindow").Call(usbCombo, 0)
		case "drivers":
			for _, h := range []uintptr{isoEdit, usbCombo, targetCombo, indexEdit, consentBox} {
				user32.NewProc("EnableWindow").Call(h, 0)
			}
		}
	}
	for i, b := range buttons {
		if !stageAllowed(uiEngine.Options, i) {
			user32.NewProc("EnableWindow").Call(b, 0)
		}
	}
	addLine("流程源码、组件版本和预演证据都保存在本项目目录。")
	addLine("开始前请核对目标盘；完整结果以部署记录和设备检查为准。")
	user32.NewProc("ShowWindow").Call(mainH, 5)
	user32.NewProc("UpdateWindow").Call(mainH)
	var m Message
	for {
		r, _, _ := user32.NewProc("GetMessageW").Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0)
		if int32(r) <= 0 {
			break
		}
		user32.NewProc("TranslateMessage").Call(uintptr(unsafe.Pointer(&m)))
		user32.NewProc("DispatchMessageW").Call(uintptr(unsafe.Pointer(&m)))
	}
}
