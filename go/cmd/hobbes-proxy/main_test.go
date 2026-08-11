package main

import (
	"bytes"
	"regexp"
	"strings"
	"testing"
	"time"
)

func TestNoArgsPrintsUsage(t *testing.T) {
	var stderr bytes.Buffer
	if code := run(nil, &stderr); code != exitUsage {
		t.Errorf("exit = %d, want %d", code, exitUsage)
	}
	if !strings.Contains(stderr.String(), "usage:") {
		t.Error("usage text missing")
	}
}

func TestUnknownCommandRejected(t *testing.T) {
	var stderr bytes.Buffer
	if code := run([]string{"resolve"}, &stderr); code != exitUsage {
		t.Errorf("exit = %d, want %d", code, exitUsage)
	}
}

func TestServeRequiresRepoAndRole(t *testing.T) {
	var stderr bytes.Buffer
	if code := run([]string{"serve", "--repo", t.TempDir()}, &stderr); code != exitUsage {
		t.Errorf("missing --role: exit = %d, want %d", code, exitUsage)
	}
	stderr.Reset()
	if code := run([]string{"serve", "--role", "implementer"}, &stderr); code != exitUsage {
		t.Errorf("missing --repo: exit = %d, want %d", code, exitUsage)
	}
}

func TestServeRejectsMissingRepoDir(t *testing.T) {
	var stderr bytes.Buffer
	code := run([]string{"serve", "--repo", "/nonexistent-hobbes", "--role", "r"}, &stderr)
	if code != exitError {
		t.Errorf("exit = %d, want %d", code, exitError)
	}
	if !strings.Contains(stderr.String(), "not a directory") {
		t.Errorf("stderr = %q", stderr.String())
	}
}

func TestParseServeDefaultsAndLogPath(t *testing.T) {
	repo := t.TempDir()
	var stderr bytes.Buffer
	cfg, logPath, err := parseServe(
		[]string{"--repo", repo, "--role", "implementer", "--session", "S-x",
			"--log-dir", "/logs", "--timeout", "30s"}, &stderr)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Role != "implementer" || cfg.Timeout != 30*time.Second {
		t.Errorf("cfg = %+v", cfg)
	}
	if logPath != "/logs/S-x/flight.jsonl" {
		t.Errorf("logPath = %q", logPath)
	}
}

func TestGeneratedSessionIDShape(t *testing.T) {
	id, err := generateSessionID()
	if err != nil {
		t.Fatal(err)
	}
	if !regexp.MustCompile(`^S-\d{8}T\d{6}Z-[0-9a-f]{4}$`).MatchString(id) {
		t.Errorf("session id %q has unexpected shape", id)
	}
	other, _ := generateSessionID()
	if id == other {
		t.Error("two generated ids collided")
	}
}
