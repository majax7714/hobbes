package policy

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// write creates path (and parents) with content.
func write(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

const minimalPolicy = "version: 1\nrules:\n  - pattern: \"x\"\n    decision: allow\n"

func TestLoadChainOrderAndLevels(t *testing.T) {
	tmp := t.TempDir()
	box := filepath.Join(tmp, "box.policy")
	repo := filepath.Join(tmp, "repo")
	write(t, box, "version: 1\nscope: box\nrules: []\n")
	write(t, filepath.Join(repo, ".hobbes/policies/repo.policy"), "version: 1\nscope: repo\nrules: []\n")
	write(t, filepath.Join(repo, "src/.hobbes/folder.policy"), "version: 1\nscope: folder\nrules: []\n")
	write(t, filepath.Join(repo, "src/auth/.hobbes/folder.policy"), minimalPolicy)
	// A sibling folder's policy must not be picked up.
	write(t, filepath.Join(repo, "docs/.hobbes/folder.policy"), minimalPolicy)

	chain, err := LoadChain(box, repo, filepath.Join(repo, "src/auth"))
	if err != nil {
		t.Fatalf("LoadChain: %v", err)
	}

	var levels, sources []string
	for _, f := range chain.Files {
		levels = append(levels, f.Level)
		sources = append(sources, f.Source)
	}
	wantLevels := []string{"box", "repo", "folder", "folder"}
	if strings.Join(levels, ",") != strings.Join(wantLevels, ",") {
		t.Errorf("levels = %v, want %v (sources: %v)", levels, wantLevels, sources)
	}
	// Deepest folder policy must come last (most specific).
	last := sources[len(sources)-1]
	if !strings.Contains(last, filepath.FromSlash("src/auth/")) {
		t.Errorf("last file is %s, want the src/auth folder policy", last)
	}
}

func TestLoadChainMissingFilesAreSkipped(t *testing.T) {
	repo := t.TempDir() // no policies anywhere, no box
	chain, err := LoadChain("", repo, repo)
	if err != nil {
		t.Fatalf("LoadChain: %v", err)
	}
	if len(chain.Files) != 0 {
		t.Errorf("got %d files, want 0", len(chain.Files))
	}
	// And an empty chain still resolves (to the escalate fallback).
	if got := chain.Resolve("anything"); got.Decision != Escalate {
		t.Errorf("empty chain resolved to %s, want escalate", got.Decision)
	}
}

func TestLoadChainExplicitBoxMustExist(t *testing.T) {
	repo := t.TempDir()
	_, err := LoadChain(filepath.Join(repo, "nope.policy"), repo, repo)
	if err == nil {
		t.Fatal("LoadChain succeeded with a missing explicit box policy")
	}
}

func TestLoadChainScopeMismatch(t *testing.T) {
	repo := t.TempDir()
	// A file declaring scope: box loaded as the repo policy must error.
	write(t, filepath.Join(repo, ".hobbes/policies/repo.policy"), "version: 1\nscope: box\nrules: []\n")
	_, err := LoadChain("", repo, repo)
	if err == nil || !strings.Contains(err.Error(), "declared scope") {
		t.Fatalf("err = %v, want declared-scope mismatch", err)
	}
}

func TestLoadChainDirOutsideRepo(t *testing.T) {
	tmp := t.TempDir()
	repo := filepath.Join(tmp, "repo")
	other := filepath.Join(tmp, "elsewhere")
	for _, d := range []string{repo, other} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	_, err := LoadChain("", repo, other)
	if err == nil || !strings.Contains(err.Error(), "not inside repo") {
		t.Fatalf("err = %v, want not-inside-repo error", err)
	}
}

func TestLoadChainPropagatesParseErrors(t *testing.T) {
	repo := t.TempDir()
	write(t, filepath.Join(repo, ".hobbes/policies/repo.policy"), "version: 1\nrules:\n  - pattern: \"x\"\n    descision: allow\n")
	_, err := LoadChain("", repo, repo)
	if err == nil || !strings.Contains(err.Error(), "descision") {
		t.Fatalf("err = %v, want strict-parse error mentioning the typo", err)
	}
}
