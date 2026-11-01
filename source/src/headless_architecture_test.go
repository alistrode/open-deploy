package main

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestHeadlessExecutionCannotCallGUI(t *testing.T) {
	files, e := filepath.Glob("*.go")
	if e != nil {
		t.Fatal(e)
	}
	functions := map[string]*ast.FuncDecl{}
	for _, name := range files {
		if strings.HasSuffix(name, "_test.go") {
			continue
		}
		file, e := parser.ParseFile(token.NewFileSet(), name, nil, 0)
		if e != nil {
			t.Fatal(e)
		}
		for _, d := range file.Decls {
			if f, ok := d.(*ast.FuncDecl); ok {
				functions[f.Name.Name] = f
			}
		}
	}
	seen := map[string]bool{}
	queue := []string{"runConfiguredStage", "commitConfiguredInstall", "configurePlan"}
	forbidden := map[string]bool{"startStage": true, "selected": true, "text": true, "control": true, "wndProc": true}
	for len(queue) > 0 {
		name := queue[0]
		queue = queue[1:]
		if seen[name] {
			continue
		}
		seen[name] = true
		f := functions[name]
		if f == nil {
			continue
		}
		ast.Inspect(f.Body, func(n ast.Node) bool {
			call, ok := n.(*ast.CallExpr)
			if !ok {
				return true
			}
			target := ""
			switch x := call.Fun.(type) {
			case *ast.Ident:
				target = x.Name
			case *ast.SelectorExpr:
				target = x.Sel.Name
				if id, ok := x.X.(*ast.Ident); ok && (id.Name == "createWindow" || id.Name == "sendMessage" || id.Name == "user32") {
					t.Errorf("headless function %s reaches GUI object %s", name, id.Name)
				}
			}
			if forbidden[target] {
				t.Errorf("headless function %s calls %s", name, target)
			}
			if functions[target] != nil {
				queue = append(queue, target)
			}
			return true
		})
	}
	guarded := false
	ast.Inspect(functions["main"].Body, func(n ast.Node) bool {
		branch, ok := n.(*ast.IfStmt)
		if !ok {
			return true
		}
		hasRun, hasCall := false, false
		ast.Inspect(branch.Cond, func(n ast.Node) bool {
			if x, ok := n.(*ast.StarExpr); ok {
				if id, ok := x.X.(*ast.Ident); ok && id.Name == "run" {
					hasRun = true
				}
			}
			return true
		})
		ast.Inspect(branch.Body, func(n ast.Node) bool {
			if c, ok := n.(*ast.CallExpr); ok {
				if id, ok := c.Fun.(*ast.Ident); ok && id.Name == "runConfiguredStage" {
					hasCall = true
				}
			}
			return true
		})
		if hasRun && hasCall {
			_, guarded = branch.Body.List[len(branch.Body.List)-1].(*ast.ReturnStmt)
		}
		return true
	})
	if !guarded {
		t.Fatal("headless dispatch can fall through to GUI")
	}
}
func TestStageLaunchersHaveNoInteractiveInput(t *testing.T) {
	for _, name := range []string{"1-Prepare.cmd", "2-Install.cmd", "3-Drivers.cmd"} {
		b, e := os.ReadFile(filepath.Join("..", "launchers", name))
		if e != nil {
			t.Fatal(e)
		}
		s := strings.ToLower(string(b))
		if !strings.Contains(s, "--run") || !strings.Contains(s, "--plan") {
			t.Fatal("launcher not configured", name)
		}
		for _, forbidden := range []string{"set /p", "choice", "pause", "--rehearsal"} {
			if strings.Contains(s, forbidden) {
				t.Fatal("interactive launcher", name)
			}
		}
	}
}
