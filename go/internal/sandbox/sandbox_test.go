package sandbox

import (
	"encoding/json"
	"regexp"
	"strings"
	"testing"
	"time"
)

func baseConfig() Config {
	return Config{
		SessionID:    "S-20260811T120000Z-abcd",
		Role:         "implementer",
		HostWorktree: "/home/u/.hobbes/sessions/S-x/worktree",
		HostSessions: "/home/u/.hobbes/sessions",
		HostProxyBin: "/home/u/hobbes/go/bin/hobbes-proxy",
	}
}

func TestNewPlanDefaults(t *testing.T) {
	p, err := NewPlan(baseConfig())
	if err != nil {
		t.Fatal(err)
	}
	if p.cfg.Image != "hobbes-session:local" || p.cfg.Network != "none" {
		t.Errorf("defaults wrong: image=%q network=%q", p.cfg.Image, p.cfg.Network)
	}
}

func TestNewPlanRequiresAbsoluteHostPaths(t *testing.T) {
	cfg := baseConfig()
	cfg.HostWorktree = "relative/path"
	if _, err := NewPlan(cfg); err == nil {
		t.Error("relative worktree must be rejected")
	}
	cfg = baseConfig()
	cfg.Role = ""
	if _, err := NewPlan(cfg); err == nil {
		t.Error("missing role must be rejected")
	}
	cfg = baseConfig()
	cfg.SessionID = ""
	if _, err := NewPlan(cfg); err == nil {
		t.Error("missing session id must be rejected")
	}
}

func TestPodmanArgsCleanEnvAndMounts(t *testing.T) {
	p, _ := NewPlan(baseConfig())
	args := p.PodmanArgs()
	joined := strings.Join(args, " ")

	// Clean env: exactly HOME and PATH, nothing host-derived.
	envs := []string{}
	for i, a := range args {
		if a == "--env" && i+1 < len(args) {
			envs = append(envs, args[i+1])
		}
	}
	if len(envs) != 2 {
		t.Fatalf("want exactly 2 env vars (HOME, PATH), got %v", envs)
	}
	if envs[0] != "HOME=/sessions/S-20260811T120000Z-abcd" {
		t.Errorf("HOME = %q", envs[0])
	}
	if !strings.HasPrefix(envs[1], "PATH=") {
		t.Errorf("second env should be PATH, got %q", envs[1])
	}

	for _, want := range []string{
		"--network none",
		"--workdir /work",
		"/home/u/.hobbes/sessions/S-x/worktree:/work:rw",
		"/home/u/.hobbes/sessions:/sessions:rw",
		"/home/u/hobbes/go/bin/hobbes-proxy:/usr/local/bin/hobbes-proxy:ro",
		"hobbes-session:local",
	} {
		if !strings.Contains(joined, want) {
			t.Errorf("podman args missing %q in:\n%s", want, joined)
		}
	}
}

func TestBoxAndClaudeMountsAreOptional(t *testing.T) {
	cfg := baseConfig()
	p, _ := NewPlan(cfg)
	if strings.Contains(strings.Join(p.PodmanArgs(), " "), "/policy/box.policy") {
		t.Error("box mount present without a host box policy")
	}
	if strings.Contains(strings.Join(p.PodmanArgs(), " "), ".claude") {
		t.Error("claude credential mounted by default — must be opt-in")
	}

	cfg.HostBoxPath = "/home/u/.hobbes/box.policy"
	cfg.HostClaude = "/home/u/.claude"
	p, _ = NewPlan(cfg)
	joined := strings.Join(p.PodmanArgs(), " ")
	if !strings.Contains(joined, "/home/u/.hobbes/box.policy:/policy/box.policy:ro") {
		t.Error("box policy not mounted ro when present")
	}
	if !strings.Contains(joined, "/home/u/.claude:/root/.claude:ro") {
		t.Error("claude credential not mounted ro when requested")
	}
}

func TestMCPConfigWiresProxyToWorktree(t *testing.T) {
	cfg := baseConfig()
	cfg.HostBoxPath = "/home/u/.hobbes/box.policy"
	p, _ := NewPlan(cfg)

	var parsed struct {
		MCPServers map[string]struct {
			Command string   `json:"command"`
			Args    []string `json:"args"`
		} `json:"mcpServers"`
	}
	if err := json.Unmarshal([]byte(p.MCPConfig()), &parsed); err != nil {
		t.Fatal(err)
	}
	h, ok := parsed.MCPServers["hobbes"]
	if !ok {
		t.Fatal("no hobbes server in MCP config")
	}
	if h.Command != "/usr/local/bin/hobbes-proxy" {
		t.Errorf("command = %q", h.Command)
	}
	a := strings.Join(h.Args, " ")
	for _, want := range []string{
		"serve", "--repo /work", "--role implementer",
		"--session S-20260811T120000Z-abcd", "--log-dir /sessions",
		"--box /policy/box.policy",
	} {
		if !strings.Contains(a, want) {
			t.Errorf("proxy args missing %q in %q", want, a)
		}
	}
}

func TestDefaultCommandForbidsRawShell(t *testing.T) {
	p, _ := NewPlan(baseConfig())
	cmd := strings.Join(p.DefaultCommand(), " ")
	if !strings.Contains(cmd, "--disallowedTools Bash") {
		t.Error("native layer must forbid Bash so exec routes through the proxy")
	}
	if !strings.Contains(cmd, "mcp__hobbes__exec") {
		t.Error("the hobbes exec tool must be allowed")
	}
	if !strings.Contains(cmd, "-p") {
		t.Error("implementer runs non-interactively (-p)")
	}
}

func TestCommandOverrideUsedForExitCheck(t *testing.T) {
	cfg := baseConfig()
	cfg.Command = []string{"python3", "/sessions/driver.py"}
	p, _ := NewPlan(cfg)
	args := p.PodmanArgs()
	if args[len(args)-2] != "python3" || args[len(args)-1] != "/sessions/driver.py" {
		t.Errorf("override command not used: %v", args[len(args)-3:])
	}
}

func TestNewIDShape(t *testing.T) {
	id, err := NewID(time.Date(2026, 8, 11, 12, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if !regexp.MustCompile(`^S-20260811T120000Z-[0-9a-f]{4}$`).MatchString(id) {
		t.Errorf("id = %q", id)
	}
}

func TestDryRunShowsPlanAndConfig(t *testing.T) {
	p, _ := NewPlan(baseConfig())
	out := p.DryRun()
	if !strings.Contains(out, "podman run") || !strings.Contains(out, "mcpServers") {
		t.Errorf("dry run should show podman argv and MCP config:\n%s", out)
	}
}
