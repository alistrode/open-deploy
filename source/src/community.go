package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// Essential drivers ship in the release; preparing media never requires torrent seeds.
type DriverFile struct {
	Path   string
	Size   int64
	SHA256 string
}
type DriverManifest struct{ Files []DriverFile }

func verifyBootstrap(root string) error {
	b, err := os.ReadFile(filepath.Join(root, "drivers-manifest.json"))
	if err != nil {
		return err
	}
	var m DriverManifest
	if err = json.Unmarshal(b, &m); err != nil {
		return err
	}
	if len(m.Files) == 0 {
		return fmt.Errorf("empty driver manifest")
	}
	for _, f := range m.Files {
		rel := filepath.FromSlash(f.Path)
		if !filepath.IsLocal(rel) || !strings.HasPrefix(f.Path, "bootstrap-drivers/") {
			return fmt.Errorf("invalid driver path: %s", f.Path)
		}
		info, err := os.Stat(filepath.Join(root, rel))
		if err != nil {
			return err
		}
		if info.Size() != f.Size {
			return fmt.Errorf("driver size mismatch: %s", f.Path)
		}
		r, err := os.Open(filepath.Join(root, rel))
		if err != nil {
			return err
		}
		h := sha256.New()
		_, err = io.Copy(h, r)
		r.Close()
		if err != nil {
			return err
		}
		if !strings.EqualFold(hex.EncodeToString(h.Sum(nil)), f.SHA256) {
			return fmt.Errorf("driver checksum mismatch: %s", f.Path)
		}
	}
	return nil
}
func fetchBootstrap(ctx context.Context, root string, output func(string)) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if err := verifyBootstrap(root); err != nil {
		return err
	}
	if output != nil {
		output("随包启动驱动校验通过；不依赖torrent下载。")
	}
	return nil
}
