package main

import (
	"bytes"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
)

func cli(args ...string) (int, string, string) {
	var stdout, stderr bytes.Buffer
	code := run(args, &stdout, &stderr)
	return code, stdout.String(), stderr.String()
}

func TestNoArgsUsage(t *testing.T) {
	if code, _, _ := cli(); code != exitUsage {
		t.Errorf("exit = %d, want %d", code, exitUsage)
	}
}

func TestStartRequiresRepoAndRole(t *testing.T) {
	if code, _, _ := cli("start", "--role", "implementer"); code != exitUsage {
		t.Errorf("missing --repo: exit = %d", code)
	}
	if code, _, _ := cli("start", "--repo", t.TempDir()); code != exitUsage {
		t.Errorf("missing --role: exit = %d", code)
	}
}

func TestStartRejectsNonGitRepo(t *testing.T) {
	fakeProxy := filepath.Join(t.TempDir(), "hobbes-proxy")
	os.WriteFile(fakeProxy, []byte("#!/bin/true\n"), 0o755)
	code, _, stderr := cli("start", "--repo", t.TempDir(), "--role", "implementer",
		"--proxy-bin", fakeProxy, "--sessions", t.TempDir(), "--dry-run")
	if code != exitError || !strings.Contains(stderr, "not a git repo") {
		t.Errorf("code=%d stderr=%q", code, stderr)
	}
}

// gitRepo makes a one-commit repo for worktree operations.
func gitRepo(t *testing.T) string {
	t.Helper()
	repo := t.TempDir()
	run := func(args ...string) {
		full := append([]string{"-C", repo, "-c", "user.name=t", "-c", "user.email=t@t"}, args...)
		if out, err := exec.Command("git", full...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v: %s", args, err, out)
		}
	}
	run("init", "-q")
	os.WriteFile(filepath.Join(repo, "README.md"), []byte("hi\n"), 0o644)
	run("add", ".")
	run("commit", "-qm", "base")
	return repo
}

func TestDryRunCreatesWorktreeShowsPlanAndCleansUp(t *testing.T) {
	repo := gitRepo(t)
	sessions := t.TempDir()
	fakeProxy := filepath.Join(t.TempDir(), "hobbes-proxy")
	os.WriteFile(fakeProxy, []byte("static\n"), 0o755)

	code, stdout, stderr := cli("start", "--repo", repo, "--role", "implementer",
		"--task", "add a helper", "--session", "S-test",
		"--proxy-bin", fakeProxy, "--sessions", sessions, "--dry-run")
	if code != 0 {
		t.Fatalf("code=%d stderr=%q", code, stderr)
	}
	// Plan is shown, with clean env and the worktree mount.
	for _, want := range []string{
		"podman run", "--network none",
		filepath.Join(sessions, "S-test", "worktree") + ":/work:rw",
		"HOME=/sessions/S-test", "mcpServers", "--disallowedTools Bash",
	} {
		if !strings.Contains(stdout, want) {
			t.Errorf("dry-run missing %q", want)
		}
	}
	// The MCP config was written host-side.
	cfg := filepath.Join(sessions, "S-test", "mcp.json")
	if _, err := os.Stat(cfg); err != nil {
		t.Errorf("MCP config not written: %v", err)
	}
	// The disposable clone was removed on teardown...
	if _, err := os.Stat(filepath.Join(sessions, "S-test", "worktree")); !os.IsNotExist(err) {
		t.Errorf("session clone not removed: %v", err)
	}
	// ...the canonical repo has no leftover session branch (a clone never
	// creates one there)...
	out, _ := exec.Command("git", "-C", repo, "branch", "--list", "hobbes/S-test").CombinedOutput()
	if strings.TrimSpace(string(out)) != "" {
		t.Errorf("canonical repo grew a session branch: %s", out)
	}
	// ...and the session dir itself (audit trail) is kept.
	if _, err := os.Stat(filepath.Join(sessions, "S-test")); err != nil {
		t.Errorf("session dir should survive teardown: %v", err)
	}
}

func TestSelinuxRelabelOnMounts(t *testing.T) {
	repo := gitRepo(t)
	fakeProxy := filepath.Join(t.TempDir(), "hobbes-proxy")
	os.WriteFile(fakeProxy, []byte("static\n"), 0o755)
	_, stdout, _ := cli("start", "--repo", repo, "--role", "implementer",
		"--session", "S-z", "--proxy-bin", fakeProxy, "--sessions", t.TempDir(), "--dry-run")
	if !strings.Contains(stdout, ":/work:rw,z") {
		t.Error("worktree mount should request an SELinux relabel (z) for rootless podman")
	}
}

func TestSessionCloneIsSelfContained(t *testing.T) {
	// A clone, not a linked worktree: its .git is a directory, so git
	// works inside a container that mounts only the worktree.
	repo := gitRepo(t)
	sessions := t.TempDir()
	fakeProxy := filepath.Join(t.TempDir(), "hobbes-proxy")
	os.WriteFile(fakeProxy, []byte("static\n"), 0o755)

	opt := options{repo: repo, role: "implementer", session: "S-clone",
		sessions: sessions, proxyBin: fakeProxy}
	_, worktree, cleanup, err := setup(opt)
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()
	info, err := os.Stat(filepath.Join(worktree, ".git"))
	if err != nil || !info.IsDir() {
		t.Errorf(".git should be a self-contained dir in the clone, got %v", err)
	}
	// git status works with no reference to any path outside the clone.
	if out, err := exec.Command("git", "-C", worktree, "status", "--short").CombinedOutput(); err != nil {
		t.Errorf("git in the clone failed: %v: %s", err, out)
	}
}

func TestRefPinsTheSessionTree(t *testing.T) {
	// V2.M6: a soft-verdict reviewer must read the head of the range
	// under review, which is not necessarily the repo's HEAD.
	repo := gitRepo(t)
	first, err := exec.Command("git", "-C", repo, "rev-parse", "HEAD").Output()
	if err != nil {
		t.Fatal(err)
	}
	os.WriteFile(filepath.Join(repo, "later.txt"), []byte("later\n"), 0o644)
	exec.Command("git", "-C", repo, "add", "-A").Run()
	exec.Command("git", "-C", repo, "commit", "-qm", "later").Run()

	sessions := t.TempDir()
	fakeProxy := filepath.Join(t.TempDir(), "hobbes-proxy")
	os.WriteFile(fakeProxy, []byte("static\n"), 0o755)
	opt := options{repo: repo, role: "reviewer", session: "S-ref",
		ref: strings.TrimSpace(string(first)), sessions: sessions, proxyBin: fakeProxy}
	_, worktree, cleanup, err := setup(opt)
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()
	if _, err := os.Stat(filepath.Join(worktree, "later.txt")); !os.IsNotExist(err) {
		t.Errorf("worktree at --ref should predate later.txt (stat err %v)", err)
	}
}

func TestSessionCloneDoesNotHardlinkObjects(t *testing.T) {
	// A local clone hardlinks objects by default, and a hardlink cannot
	// cross a filesystem — so a repo on a different device than the
	// sessions dir failed to clone at all. Asserting link count rather
	// than staging two filesystems: unlinked objects are the property
	// that makes the cross-device case work, and it holds anywhere.
	repo := gitRepo(t)
	fakeProxy := filepath.Join(t.TempDir(), "hobbes-proxy")
	os.WriteFile(fakeProxy, []byte("static\n"), 0o755)

	opt := options{repo: repo, role: "implementer", session: "S-links",
		sessions: t.TempDir(), proxyBin: fakeProxy}
	_, worktree, cleanup, err := setup(opt)
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()

	objects := 0
	err = filepath.WalkDir(filepath.Join(worktree, ".git", "objects"),
		func(path string, d fs.DirEntry, err error) error {
			if err != nil || d.IsDir() {
				return err
			}
			info, err := d.Info()
			if err != nil {
				return err
			}
			objects++
			if st, ok := info.Sys().(*syscall.Stat_t); ok && st.Nlink > 1 {
				t.Errorf("%s has %d links; the clone must not hardlink into the "+
					"canonical repo (breaks across filesystems)", path, st.Nlink)
			}
			return nil
		})
	if err != nil {
		t.Fatal(err)
	}
	if objects == 0 {
		t.Fatal("no object files found in the clone; the assertion checked nothing")
	}
}

func TestMissingProxyBinIsAClearError(t *testing.T) {
	repo := gitRepo(t)
	code, _, stderr := cli("start", "--repo", repo, "--role", "implementer",
		"--proxy-bin", "/nonexistent/hobbes-proxy", "--sessions", t.TempDir(), "--dry-run")
	if code != exitError || !strings.Contains(stderr, "proxy binary") {
		t.Errorf("code=%d stderr=%q", code, stderr)
	}
}

func TestCommandOverrideParsedAfterDoubleDash(t *testing.T) {
	repo := gitRepo(t)
	fakeProxy := filepath.Join(t.TempDir(), "hobbes-proxy")
	os.WriteFile(fakeProxy, []byte("static\n"), 0o755)
	code, stdout, stderr := cli("start", "--repo", repo, "--role", "implementer",
		"--session", "S-ov", "--proxy-bin", fakeProxy, "--sessions", t.TempDir(),
		"--dry-run", "--", "python3", "/sessions/driver.py")
	if code != 0 {
		t.Fatalf("code=%d stderr=%q", code, stderr)
	}
	if !strings.Contains(stdout, "python3 /sessions/driver.py") {
		t.Errorf("override command not in plan:\n%s", stdout)
	}
	if strings.Contains(stdout, "claude") {
		t.Error("override should replace the default claude command")
	}
}
