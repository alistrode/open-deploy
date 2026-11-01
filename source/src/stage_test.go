package main

import "testing"

func TestReadOnlyLaunchCannotEnableLiveExecution(t *testing.T) {
	for _, flags := range [][3]bool{{true, false, false}, {false, true, false}, {false, false, true}} {
		if validateLaunch(true, flags[0], flags[1], flags[2], "prepare") == nil {
			t.Fatal("live mode accepted with a read-only command")
		}
	}
	if validateLaunch(false, true, false, false, "prepare") != nil {
		t.Fatal("normal rehearsal rejected")
	}
}

func TestLiveStageIsolation(t *testing.T) {
	for expected, stage := range []string{"prepare", "install", "drivers"} {
		for button := 0; button < 3; button++ {
			if stageAllowed(Options{Live: true, Stage: stage}, button) != (button == expected) {
				t.Fatalf("stage %s incorrectly authorizes button %d", stage, button)
			}
		}
	}
	if stageAllowed(Options{Live: true, Stage: "unknown"}, 0) {
		t.Fatal("unknown live stage accepted")
	}
}
