package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
)

// Query actual Windows device problem codes after SDIO exits. The command is
// constant: no device names, filesystem paths or user input enter shell code.
func verifyDeviceHealth(root string) error {
	cmd := exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", `$ErrorActionPreference='Stop'; $bad=@(Get-CimInstance Win32_PnPEntity | Where-Object { $_.ConfigManagerErrorCode -ne 0 }); ConvertTo-Json -InputObject $bad -Depth 3; if ($bad.Count -gt 0) { exit 3 }`)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	result, err := cmd.CombinedOutput()
	if mkErr := os.MkdirAll(filepath.Join(root, "evidence"), 0755); mkErr != nil {
		return mkErr
	}
	if writeErr := os.WriteFile(filepath.Join(root, "evidence", "device-health.json"), result, 0644); writeErr != nil {
		return writeErr
	}
	if err != nil {
		return fmt.Errorf("device health check did not pass; inspect evidence/device-health.json: %w", err)
	}
	return nil
}
