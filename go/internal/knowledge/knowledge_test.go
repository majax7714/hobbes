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

// --- module docs (ADR-019) -------------------------------------------------

// writeModuleDoc files a narrative module-doc artifact for app.core whose
// sources stamp the *current* working-tree blob of src/app/core.py.
func writeModuleDoc(t *testing.T, repo string) {
	t.Helper()
	src := filepath.Join(repo, "src", "app")
	if err := os.MkdirAll(src, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(src, "core.py"), []byte("def run():\n    return 1\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	out, err := exec.Command("git", "-C", repo, "hash-object", "--", "src/app/core.py").Output()
	if err != nil {
		t.Fatal(err)
	}
	doc := map[string]any{
		"schema_version": 1, "kind": "module-doc",
		"id": "app.core", "path": "src/app/core.py",
		"sha": "c0ffee0000000000000000000000000000000000", "dirty": false,
		"sources": []map[string]any{
			{"path": "src/app/core.py", "blob_sha": strings.TrimSpace(string(out))},
		},
		"purpose": map[string]any{
			"text": "runs the core computation",
			"pins": []map[string]any{{"path": "src/app/core.py", "line": 1}},
		},
		"responsibilities": []map[string]any{
			{"text": "returns the answer",
				"pins": []map[string]any{{"path": "src/app/core.py", "line": 2}}},
		},
		"gotchas": []map[string]any{},
	}
	dir := filepath.Join(repo, ".hobbes", "derived", "docs", "modules")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	data, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "app.core.json"), data, 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestModuleDocRendersPinnedClaims(t *testing.T) {
	repo := fixtureRepo(t)
	writeModuleDoc(t, repo)
	out, err := Open(repo).ModuleDoc("app.core")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{
		"knowledge from narrate @ c0ffee000000",
		"module app.core (src/app/core.py)",
		"purpose: runs the core computation  [src/app/core.py:1]",
		"responsibilities:",
		"- returns the answer  [src/app/core.py:2]",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("missing %q in:\n%s", want, out)
		}
	}
	if strings.Contains(out, "STALE") || strings.Contains(out, "gotchas") {
		t.Errorf("fresh doc with no gotchas rendered wrong:\n%s", out)
	}
}

func TestModuleDocBlobStaleWarns(t *testing.T) {
	repo := fixtureRepo(t)
	writeModuleDoc(t, repo)
	// An uncommitted edit to a cited file must flip the badge (ADR-019).
	if err := os.WriteFile(filepath.Join(repo, "src", "app", "core.py"), []byte("edited = True\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	out, err := Open(repo).ModuleDoc("app.core")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "WARNING: STALE") || !strings.Contains(out, "src/app/core.py") ||
		!strings.Contains(out, "hobbes narrate") {
		t.Errorf("want blob-level stale warning naming the file:\n%s", out)
	}
}

func TestModuleDocDeletedSourceIsStale(t *testing.T) {
	repo := fixtureRepo(t)
	writeModuleDoc(t, repo)
	if err := os.Remove(filepath.Join(repo, "src", "app", "core.py")); err != nil {
		t.Fatal(err)
	}
	out, err := Open(repo).ModuleDoc("app.core")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "WARNING: STALE") {
		t.Errorf("deleted source should read stale:\n%s", out)
	}
}

func TestModuleDocUnknownIdSuggests(t *testing.T) {
	repo := fixtureRepo(t)
	writeModuleDoc(t, repo)
	out, err := Open(repo).ModuleDoc("core")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, `no module doc for "core"`) || !strings.Contains(out, "app.core") {
		t.Errorf("want near-miss suggestion:\n%s", out)
	}
}

func TestModuleDocNoneGeneratedSaysRunNarrate(t *testing.T) {
	repo := fixtureRepo(t)
	_, err := Open(repo).ModuleDoc("app.core")
	if err == nil || !strings.Contains(err.Error(), "hobbes narrate") {
		t.Errorf("want run-narrate error, got %v", err)
	}
}

func TestModuleDocRejectsTraversalIds(t *testing.T) {
	repo := fixtureRepo(t)
	// "/"-bearing ids are legal (TS/JS path ids, ADR-021); traversal is not.
	for _, id := range []string{"../evil", "..", "x/../y", "/abs", `a\b`, "a//b", "a/./b", ""} {
		if _, err := Open(repo).ModuleDoc(id); err == nil {
			t.Errorf("id %q should be rejected", id)
		}
	}
}

func TestModuleDocNestedTsId(t *testing.T) {
	repo := fixtureRepo(t)
	writeModuleDoc(t, repo) // creates docs/modules/app.core.json too
	doc := map[string]any{
		"schema_version": 1, "kind": "module-doc",
		"id": "src/flow", "path": "src/flow.js",
		"sha": "beef000000000000000000000000000000000000", "dirty": false,
		"sources": []map[string]any{},
		"purpose": map[string]any{
			"text": "pure auth-flow logic",
			"pins": []map[string]any{{"path": "src/app/core.py", "line": 1}},
		},
		"responsibilities": []map[string]any{},
		"gotchas":          []map[string]any{},
	}
	dir := filepath.Join(repo, ".hobbes", "derived", "docs", "modules", "src")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	data, _ := json.Marshal(doc)
	if err := os.WriteFile(filepath.Join(dir, "flow.json"), data, 0o644); err != nil {
		t.Fatal(err)
	}
	out, err := Open(repo).ModuleDoc("src/flow")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "module src/flow (src/flow.js)") {
		t.Errorf("nested id not rendered:\n%s", out)
	}
	// The nested id shows up in near-miss suggestions too.
	miss, err := Open(repo).ModuleDoc("flow")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(miss, "src/flow") {
		t.Errorf("nested id missing from suggestions:\n%s", miss)
	}
}
