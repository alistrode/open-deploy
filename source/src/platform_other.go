//go:build !windows

package main

import (
	"errors"
	"os"
)

// Non-Windows builds support portable unit tests, never Windows installation.
func isPE() bool                             { return false }
func readDisk(int) (Disk, error)             { return Disk{}, errors.New("Windows required") }
func volumeDisk(string) int                  { return -1 }
func waitDiskVolume(int) string              { return "" }
func runSDIO(string, ...string) error        { return errors.New("Windows required") }
func listDisks() []Disk                      { return nil }
func machineUUID() (string, error)           { return "", errors.New("Windows required") }
func verifyInstalledVolumes(int) error       { return errors.New("Windows required") }
func lockWorkflow(string) (func(), error)    { return nil, errors.New("Windows required") }
func replaceStateFile(from, to string) error { return os.Rename(from, to) }
func liveRunner(string, ...string) error     { return errors.New("Windows required") }
