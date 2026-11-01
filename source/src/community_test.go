package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func testDriverPayload(t *testing.T, root string) {
	t.Helper()
	data := []byte("driver fixture")
	p := filepath.Join(root, "bootstrap-drivers", "test.inf")
	if err := os.MkdirAll(filepath.Dir(p), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, data, 0644); err != nil {
		t.Fatal(err)
	}
	h := sha256.Sum256(data)
	b, _ := json.Marshal(DriverManifest{Files: []DriverFile{{"bootstrap-drivers/test.inf", int64(len(data)), hex.EncodeToString(h[:])}}})
	if err := os.WriteFile(filepath.Join(root, "drivers-manifest.json"), b, 0644); err != nil {
		t.Fatal(err)
	}
}
func TestBootstrapRejectsCorruptionAndMissingPayload(t *testing.T) {
	root := t.TempDir()
	if verifyBootstrap(root) == nil {
		t.Fatal("missing payload accepted")
	}
	testDriverPayload(t, root)
	if err := verifyBootstrap(root); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "bootstrap-drivers", "test.inf"), []byte("driver corrupt"), 0644); err != nil {
		t.Fatal(err)
	}
	if verifyBootstrap(root) == nil {
		t.Fatal("same-size corrupt driver accepted")
	}
}
func TestBootstrapRejectsManifestTraversal(t *testing.T) {
	root := t.TempDir()
	b, _ := json.Marshal(DriverManifest{Files: []DriverFile{{"bootstrap-drivers/../../outside.inf", 1, "x"}}})
	os.WriteFile(filepath.Join(root, "drivers-manifest.json"), b, 0644)
	if verifyBootstrap(root) == nil {
		t.Fatal("manifest traversal accepted")
	}
}
