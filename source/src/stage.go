package main

import "errors"

func validateLaunch(live, rehearsal, selfTest, fetch bool, stage string) error {
	if live && (rehearsal || selfTest || fetch) {
		return errors.New("live execution cannot be combined with rehearsal, self-test or download-only mode")
	}
	if stage != "prepare" && stage != "install" && stage != "drivers" {
		return errors.New("unknown deployment stage")
	}
	return nil
}

// Keep both button state and command dispatch within the selected live stage.
func stageAllowed(o Options, index int) bool {
	if index < 0 || index > 2 {
		return false
	}
	return !o.Live || o.Stage == []string{"prepare", "install", "drivers"}[index]
}
