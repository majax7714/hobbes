// Package sandbox builds the rootless-podman invocation that launches an
// agent session (M4, ADR-018): a fresh git worktree mounted rw, the
// session-state dir mounted rw for the flight recorder and escalation
// queue, the box policy mounted ro, a clean environment, and Claude Code
// wired to the hobbes-proxy MCP server. The Plan is pure data — it builds
// the podman argv and MCP config without running anything, so the whole
// design is inspectable via `hobbes-session --dry-run` and unit-testable.
package sandbox

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"path/filepath"
	"strings"
	"time"
)

// In-container mount points. Fixed so the MCP config and podman args agree.
const (
	WorkDir      = "/work"     // the session worktree, rw
	SessionsRoot = "/sessions" // ~/.hobbes/sessions, rw (logs + escalations)
	ProxyPath    = "/usr/local/bin/hobbes-proxy"
	BoxPath      = "/policy/box.policy"         // ro, only when a host box policy exists
	DerivedDir   = WorkDir + "/.hobbes/derived" // ro, the knowledge layer
	ClaudeHome   = "/root/.claude"              // session's own credential, ro, opt-in
)

// Config is the wrapper's validated input.
type Config struct {
	SessionID    string // generated when empty
	Role         string // required
	Image        string // session image (default hobbes-session:local)
	Task         string // the implementer's prompt (for the default cmd)
	Network      string // podman --network (default "none")
	HostWorktree string // absolute host path of the session worktree
	HostSessions string // absolute host ~/.hobbes/sessions
	HostProxyBin string // absolute host path of the static proxy binary
	HostBoxPath  string // host box policy, "" when none
	HostClaude   string // host ~/.claude to mount ro, "" to omit
	// HostDerived is the host repo's .hobbes/derived, mounted ro into the
	// worktree so the knowledge tools have artifacts to answer from — a
	// fresh worktree has none, because derived/ is gitignored. "" omits it.
	HostDerived string
	Timeout     time.Duration // proxy per-command wall clock, 0 = proxy default
	Escalation  time.Duration // proxy park deadline, 0 = proxy default
	// Command overrides the in-container command (the exit check passes a
	// scripted implementer here); empty means the default Claude Code call.
	Command []string
}

// Plan is a ready-to-run sandbox invocation.
type Plan struct {
	cfg Config
}

// NewID mints a sortable, collision-safe session id (matches ADR-014).
func NewID(now time.Time) (string, error) {
	var b [2]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	return fmt.Sprintf("S-%s-%s",
		now.UTC().Format("20060102T150405Z"), hex.EncodeToString(b[:])), nil
}

// NewPlan validates cfg and returns a Plan.
func NewPlan(cfg Config) (*Plan, error) {
	if cfg.Role == "" {
		return nil, fmt.Errorf("sandbox: role is required")
	}
	if cfg.SessionID == "" {
		return nil, fmt.Errorf("sandbox: session id is required")
	}
	for name, path := range map[string]string{
		"worktree":     cfg.HostWorktree,
		"sessions dir": cfg.HostSessions,
		"proxy binary": cfg.HostProxyBin,
	} {
		if path == "" || !filepath.IsAbs(path) {
			return nil, fmt.Errorf("sandbox: %s must be an absolute host path, got %q", name, path)
		}
	}
	if cfg.Image == "" {
		cfg.Image = "hobbes-session:local"
	}
	if cfg.Network == "" {
		cfg.Network = "none"
	}
	return &Plan{cfg: cfg}, nil
}

// sessionHome is the in-container HOME: the session's own dir under the
// mounted sessions root, so anything HOME-relative stays box-side.
func (p *Plan) sessionHome() string {
	return SessionsRoot + "/" + p.cfg.SessionID
}

// mcpConfigContainerPath is where the generated MCP config lands (written
// host-side into the session dir, visible here through the mount).
func (p *Plan) mcpConfigContainerPath() string {
	return p.sessionHome() + "/mcp.json"
}

// MCPConfigHostPath is where the wrapper must write the MCP config on the
// host for the container to read it.
func (p *Plan) MCPConfigHostPath() string {
	return filepath.Join(p.cfg.HostSessions, p.cfg.SessionID, "mcp.json")
}

// MCPConfig is the Claude Code MCP config JSON: one server, hobbes, run as
// the policy proxy over stdio against the mounted worktree.
func (p *Plan) MCPConfig() string {
	args := []string{"serve",
		"--repo", WorkDir,
		"--role", p.cfg.Role,
		"--session", p.cfg.SessionID,
		"--log-dir", SessionsRoot,
	}
	if p.cfg.HostBoxPath != "" {
		args = append(args, "--box", BoxPath)
	}
	if p.cfg.Timeout > 0 {
		args = append(args, "--timeout", p.cfg.Timeout.String())
	}
	if p.cfg.Escalation > 0 {
		args = append(args, "--escalation-timeout", p.cfg.Escalation.String())
	}
	cfg := map[string]any{
		"mcpServers": map[string]any{
			"hobbes": map[string]any{
				"command": ProxyPath,
				"args":    args,
			},
		},
	}
	out, _ := json.MarshalIndent(cfg, "", "  ")
	return string(out)
}

// ReadOnlyRoles are the roles whose worktree is mounted read-only.
// Architecture §6: "a reviewer session gets read-only mounts + the
// graph-diff tools". §5.2 puts the OS sandbox first among the
// enforcement tiers — the one that actually guarantees anything — so a
// reviewer's inability to write is a mount flag, not a policy rule an
// agent might talk its way around.
var ReadOnlyRoles = map[string]bool{"reviewer": true}

// WorktreeMode is "ro" or "rw" for this session's role.
func (p *Plan) WorktreeMode() string {
	if ReadOnlyRoles[p.cfg.Role] {
		return "ro"
	}
	return "rw"
}

// mounts returns the -v specs, in a stable order. The `z` suffix requests
// an SELinux relabel to a shared container label, which rootless podman on
// an enforcing host (Fedora, D2) requires to read or write a bind mount.
func (p *Plan) mounts() []string {
	m := []string{
		// The session dir stays rw for every role: the flight recorder
		// and escalation queue must be writable even when the source is
		// not, or a read-only session could not be audited.
		p.cfg.HostWorktree + ":" + WorkDir + ":" + p.WorktreeMode() + ",z",
		p.cfg.HostSessions + ":" + SessionsRoot + ":rw,z",
		p.cfg.HostProxyBin + ":" + ProxyPath + ":ro,z",
	}
	if p.cfg.HostBoxPath != "" {
		m = append(m, p.cfg.HostBoxPath+":"+BoxPath+":ro,z")
	}
	if p.cfg.HostClaude != "" {
		m = append(m, p.cfg.HostClaude+":"+ClaudeHome+":ro,z")
	}
	if p.cfg.HostDerived != "" {
		// Read-only for every role, including the implementer: derived
		// artifacts are the pipeline's output, and a session that could
		// edit them could edit the map it is being judged against.
		m = append(m, p.cfg.HostDerived+":"+DerivedDir+":ro,z")
	}
	return m
}

// knowledgeTools is the §6 tool set every role gets: read-only queries
// over the derived layer, so a session starts oriented instead of
// grepping (ADR-017, completed by list_invariants at M8).
var knowledgeTools = []string{
	"mcp__hobbes__graph_neighborhood",
	"mcp__hobbes__who_calls",
	"mcp__hobbes__tests_guarding",
	"mcp__hobbes__get_module_doc",
	"mcp__hobbes__list_invariants",
}

// allowedTools is the native tool allowlist for a role. A reviewer gets
// no Edit/Write and no exec: §6 makes it a read-only role, and its
// worktree is already mounted ro, so offering write tools would only
// produce confusing failures instead of a clear boundary.
func (p *Plan) allowedTools() []string {
	tools := append([]string{}, knowledgeTools...)
	if ReadOnlyRoles[p.cfg.Role] {
		return append(tools, "Read", "Grep", "Glob")
	}
	return append([]string{"mcp__hobbes__exec"}, append(tools, "Edit", "Write", "Read")...)
}

// DefaultCommand is the Claude Code invocation used when the caller
// doesn't override Command. Bash is disallowed at the native layer
// (§5.2 tier 3) so the agent must reach the shell through the
// policy-gated hobbes exec tool; the rest of the allowlist is the role's.
func (p *Plan) DefaultCommand() []string {
	mode := "acceptEdits"
	if ReadOnlyRoles[p.cfg.Role] {
		// Nothing to accept: a read-only role that is asked to confirm an
		// edit has already gone wrong.
		mode = "default"
	}
	return []string{
		"claude", "-p", p.cfg.Task,
		"--mcp-config", p.mcpConfigContainerPath(),
		"--permission-mode", mode,
		"--disallowedTools", "Bash",
		"--allowedTools", strings.Join(p.allowedTools(), ","),
	}
}

// command is the in-container command: the override, or the default.
func (p *Plan) command() []string {
	if len(p.cfg.Command) > 0 {
		return p.cfg.Command
	}
	return p.DefaultCommand()
}

// PodmanArgs is the full argv for `podman`, ready to exec. Env is
// deliberately just HOME and PATH — rootless podman passes no host env, so
// no repo or infra secret can reach the session (ADR-018, §5.2).
func (p *Plan) PodmanArgs() []string {
	args := []string{
		"run", "--rm",
		"--network", p.cfg.Network,
		"--env", "HOME=" + p.sessionHome(),
		"--env", "PATH=/usr/local/bin:/usr/bin:/bin",
		"--workdir", WorkDir,
	}
	for _, m := range p.mounts() {
		args = append(args, "-v", m)
	}
	args = append(args, p.cfg.Image)
	args = append(args, p.command()...)
	return args
}

// DryRun renders the plan as inspectable text (ADR-018): the podman argv
// and the MCP config the agent will receive.
func (p *Plan) DryRun() string {
	var b strings.Builder
	fmt.Fprintf(&b, "session:  %s (role %s)\n", p.cfg.SessionID, p.cfg.Role)
	fmt.Fprintf(&b, "image:    %s   network: %s\n", p.cfg.Image, p.cfg.Network)
	fmt.Fprintf(&b, "worktree: %s (%s)\n", p.cfg.HostWorktree, p.WorktreeMode())
	b.WriteString("\npodman " + strings.Join(p.PodmanArgs(), " ") + "\n")
	b.WriteString("\nMCP config (" + p.MCPConfigHostPath() + "):\n")
	b.WriteString(p.MCPConfig() + "\n")
	return b.String()
}

// SessionID exposes the id for the caller (worktree/dir naming).
func (p *Plan) SessionID() string { return p.cfg.SessionID }
