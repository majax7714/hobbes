package knowledge

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// fixtureRepo builds a git repo with hand-written derived artifacts.
func fixtureRepo(t *testing.T) string {
	t.Helper()
	repo := t.TempDir()
	git := func(args ...string) string {
		full := append([]string{"-C", repo, "-c", "user.name=t", "-c", "user.email=t@t"}, args...)
		out, err := exec.Command("git", full...).Output()
		if err != nil {
			t.Fatalf("git %v: %v", args, err)
		}
		return strings.TrimSpace(string(out))
	}
	git("init", "-q")
	git("commit", "-qm", "base", "--allow-empty")
	sha := git("rev-parse", "HEAD")

	graph := map[string]any{
		"sha": sha, "dirty": false,
		"nodes": []map[string]any{
			{"id": "app.core", "kind": "module", "path": "src/app/core.py"},
			{"id": "app.api", "kind": "module", "path": "src/app/api.py"},
			{"id": "ext:requests", "kind": "external"},
			{"id": "env:APP_MODE", "kind": "env", "name": "APP_MODE"},
		},
		"module_edges": []map[string]any{
			{"from": "app.api", "to": "app.core", "type": "imports",
				"evidence": []map[string]any{{"path": "src/app/api.py", "line": 3}}},
			{"from": "app.core", "to": "ext:requests", "type": "imports",
				"evidence": []map[string]any{{"path": "src/app/core.py", "line": 1}}},
			{"from": "app.core", "to": "env:APP_MODE", "type": "env-read",
				"evidence": []map[string]any{{"path": "src/app/core.py", "line": 9}}},
		},
		"symbols": []map[string]any{
			{"id": "app.core.run", "module": "app.core", "kind": "function", "line": 5},
			{"id": "app.api.handler", "module": "app.api", "kind": "function", "line": 7},
		},
		"symbol_edges": []map[string]any{
			{"from": "app.api.handler", "to": "app.core.run", "type": "calls",
				"evidence": []map[string]any{{"path": "src/app/api.py", "line": 9}}},
		},
	}
	tests := map[string]any{
		"sha": sha, "dirty": false,
		"tests": []map[string]any{
			{"id": "tests/test_core.py::test_run", "file": "tests/test_core.py",
				"line": 4, "reaches": []string{"app.core.run"},
				"reaches_modules": []string{"app.core"}},
			{"id": "tests/test_api.py::test_handler", "file": "tests/test_api.py",
				"line": 8, "reaches": []string{"app.api.handler"},
				"reaches_modules": []string{"app.api"}},
		},
	}
	derived := filepath.Join(repo, ".hobbes", "derived")
	if err := os.MkdirAll(derived, 0o755); err != nil {
		t.Fatal(err)
	}
	for name, doc := range map[string]any{"graph.json": graph, "tests.json": tests} {
		data, err := json.Marshal(doc)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(derived, name), data, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return repo
}

func TestNeighborhoodListsBothDirectionsWithProvenance(t *testing.T) {
	s := Open(fixtureRepo(t))
	out, err := s.Neighborhood("app.core")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{
		"app.core (module, src/app/core.py)",
		"-imports-> ext:requests",
		"-env-read-> env:APP_MODE",
		"<-imports- app.api",
		"[src/app/api.py:3]",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("missing %q in:\n%s", want, out)
		}
	}
	if strings.Contains(out, "WARNING") {
		t.Errorf("fresh artifacts flagged stale:\n%s", out)
	}
}

func TestNeighborhoodUnknownNodeSuggests(t *testing.T) {
	s := Open(fixtureRepo(t))
	out, err := s.Neighborhood("core")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, `no node "core"`) || !strings.Contains(out, "app.core") {
		t.Errorf("want near-miss suggestion:\n%s", out)
	}
}

func TestWhoCallsWithEvidence(t *testing.T) {
	s := Open(fixtureRepo(t))
	out, err := s.WhoCalls("app.core.run")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "app.api.handler") || !strings.Contains(out, "[src/app/api.py:9]") {
		t.Errorf("caller with provenance missing:\n%s", out)
	}
}

func TestWhoCallsKnownSymbolWithoutCallers(t *testing.T) {
	s := Open(fixtureRepo(t))
	out, err := s.WhoCalls("app.api.handler")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "no recorded callers") {
		t.Errorf("want the static-edges caveat, got:\n%s", out)
	}
}

func TestTestsGuardingByModuleAndByPath(t *testing.T) {
	s := Open(fixtureRepo(t))
	byModule, err := s.TestsGuarding("app.core")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(byModule, "tests/test_core.py::test_run") ||
		strings.Contains(byModule, "test_api") {
		t.Errorf("module query wrong:\n%s", byModule)
	}
	byPath, err := s.TestsGuarding("src/app")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(byPath, "test_run") || !strings.Contains(byPath, "test_handler") {
		t.Errorf("path-prefix query should span both modules:\n%s", byPath)
	}
}

func TestTestsGuardingUnguardedModuleSaysSo(t *testing.T) {
	repo := fixtureRepo(t)
	// Drop the core test so app.core is unguarded.
	path := filepath.Join(repo, ".hobbes", "derived", "tests.json")
	data, _ := os.ReadFile(path)
	var doc map[string]any
	json.Unmarshal(data, &doc)
	doc["tests"] = []any{}
	out, _ := json.Marshal(doc)
	os.WriteFile(path, out, 0o644)

	s := Open(repo)
	answer, err := s.TestsGuarding("app.core")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(answer, "unguarded") {
		t.Errorf("want the unguarded warning:\n%s", answer)
	}
}

func TestStaleArtifactsWarn(t *testing.T) {
	repo := fixtureRepo(t)
	git := append([]string{"-C", repo, "-c", "user.name=t", "-c", "user.email=t@t"},
		"commit", "-qm", "moved on", "--allow-empty")
	if err := exec.Command("git", git...).Run(); err != nil {
		t.Fatal(err)
	}
	out, err := Open(repo).Neighborhood("app.core")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "WARNING") || !strings.Contains(out, "stale") {
		t.Errorf("moved HEAD must flag staleness:\n%s", out)
	}
}

func TestMissingArtifactsSayRunIngest(t *testing.T) {
	repo := t.TempDir()
	_, err := Open(repo).Neighborhood("x")
	if err == nil || !strings.Contains(err.Error(), "hobbes ingest") {
		t.Errorf("err = %v, want run-ingest hint", err)
	}
}
