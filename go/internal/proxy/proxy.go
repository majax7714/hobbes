// Package proxy implements the M4 tool proxy (architecture §5.2 tier 2):
// the MCP server standing between an agent session and the machine. Agents
// get no raw shell — they call the exec tool, the proxy resolves the
// command against the merged policy chain (internal/policy, ADR-002),
// executes or refuses or escalates, and logs every call to the session's
// flight recorder (internal/recorder, ADR-015). One proxy process serves
// one session (ADR-014).
package proxy

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/majax7714/hobbes/go/internal/policy"
	"github.com/majax7714/hobbes/go/internal/recorder"
)

// outputCap is the per-stream capture limit for exec results (ADR-015):
// a runaway command must not flood the agent's context window.
const outputCap = 50 * 1024

// DefaultTimeout bounds one exec call unless the caller overrides it.
const DefaultTimeout = 10 * time.Minute

// Config identifies the session this proxy serves and where it enforces.
type Config struct {
	Session  string
	Role     string
	RepoRoot string        // absolute repo root; commands are confined to it
	BoxPath  string        // box policy path, "" for none (ADR-003 rules)
	Timeout  time.Duration // per-command wall clock; 0 means DefaultTimeout
	Rec      *recorder.Recorder
}

// Server owns the exec handler for one session.
type Server struct {
	cfg Config
}

// New validates the config and returns a Server.
func New(cfg Config) (*Server, error) {
	if cfg.Session == "" || cfg.Role == "" {
		return nil, fmt.Errorf("proxy: session and role are required")
	}
	root, err := filepath.Abs(cfg.RepoRoot)
	if err != nil {
		return nil, fmt.Errorf("proxy: %w", err)
	}
	cfg.RepoRoot = root
	if cfg.Timeout <= 0 {
		cfg.Timeout = DefaultTimeout
	}
	if cfg.Rec == nil {
		return nil, fmt.Errorf("proxy: a flight recorder is required — the proxy never runs unaudited")
	}
	return &Server{cfg: cfg}, nil
}

// ExecArgs is the exec tool's input schema (generated for the agent by the
// MCP SDK from these tags).
type ExecArgs struct {
	Command string `json:"command" jsonschema:"the shell command to run (via /bin/sh -c)"`
	Dir     string `json:"dir,omitempty" jsonschema:"working directory relative to the repo root (default: the repo root)"`
}

// MCP returns the MCP server exposing this session's tools.
func (s *Server) MCP() *mcp.Server {
	srv := mcp.NewServer(&mcp.Implementation{Name: "hobbes-proxy", Version: "0.1.0"}, nil)
	mcp.AddTool(srv, &mcp.Tool{
		Name: "exec",
		Description: "Run a shell command in the session repo, gated by the " +
			"merged Hobbes policy chain (allow | deny | escalate). Denied and " +
			"escalated commands do not run. Every call is logged to the " +
			"session flight recorder.",
	}, s.handleExec)
	return srv
}

// errResult wraps a message as a tool-level error the agent can see.
func errResult(format string, args ...any) *mcp.CallToolResult {
	return &mcp.CallToolResult{
		IsError: true,
		Content: []mcp.Content{&mcp.TextContent{Text: fmt.Sprintf(format, args...)}},
	}
}

// handleExec is the exec tool: confine dir → resolve policy → act → log.
func (s *Server) handleExec(ctx context.Context, _ *mcp.CallToolRequest, args ExecArgs) (*mcp.CallToolResult, any, error) {
	if strings.TrimSpace(args.Command) == "" {
		return errResult("exec: empty command"), nil, nil
	}

	// Dir confinement is a proxy error, not a policy question (ADR-015).
	dir := filepath.Join(s.cfg.RepoRoot, filepath.FromSlash(args.Dir))
	rel, err := filepath.Rel(s.cfg.RepoRoot, dir)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return errResult("exec: dir %q escapes the repo root", args.Dir), nil, nil
	}

	// The chain is loaded per call: folder policies depend on dir, and a
	// mid-session policy edit should take effect on the next command.
	chain, err := policy.LoadChain(s.cfg.BoxPath, s.cfg.RepoRoot, dir)
	if err != nil {
		return errResult("exec: loading policy chain: %v", err), nil, nil
	}
	res := chain.Resolve(args.Command)

	ev := recorder.Event{
		Session: s.cfg.Session,
		Role:    s.cfg.Role,
		Tool:    "exec",
		// The raw command, not res.Command: normalization is for
		// matching, and may not preserve quoting semantics.
		Argv:       []string{"/bin/sh", "-c", args.Command},
		PolicyRule: policyRuleLabel(res),
		Decision:   string(res.Decision),
		SHA:        headSHA(s.cfg.RepoRoot),
	}

	switch res.Decision {
	case policy.Deny:
		result := errResult("policy denied: %s%s\nThe command was NOT run.",
			ev.PolicyRule, reasonSuffix(res))
		return s.record(ev, result), nil, nil
	case policy.Escalate:
		result := errResult("policy escalation: %s%s\n"+
			"This command requires human approval and was NOT run. "+
			"(The escalation queue lands in M4 chunk 2; until then, ask the "+
			"human to run it or to adjust policy.)",
			ev.PolicyRule, reasonSuffix(res))
		return s.record(ev, result), nil, nil
	}

	result := s.run(ctx, args.Command, dir, &ev)
	return s.record(ev, result), nil, nil
}

// run executes an allowed command and fills the event's exit code.
func (s *Server) run(ctx context.Context, command, dir string, ev *recorder.Event) *mcp.CallToolResult {
	cctx, cancel := context.WithTimeout(ctx, s.cfg.Timeout)
	defer cancel()

	cmd := exec.CommandContext(cctx, "/bin/sh", "-c", command)
	cmd.Dir = dir
	// Kill the whole process group on timeout, not just the shell.
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	cmd.WaitDelay = 5 * time.Second

	stdout := &cappedBuffer{cap: outputCap}
	stderr := &cappedBuffer{cap: outputCap}
	cmd.Stdout = stdout
	cmd.Stderr = stderr

	runErr := cmd.Run()
	if cmd.ProcessState == nil {
		// Spawn failure: nothing ran, exit stays null (ADR-015).
		return errResult("exec: failed to start: %v", runErr)
	}
	exit := cmd.ProcessState.ExitCode()
	ev.Exit = &exit

	var b strings.Builder
	fmt.Fprintf(&b, "exit %d", exit)
	if cctx.Err() == context.DeadlineExceeded {
		fmt.Fprintf(&b, " (killed: timed out after %s)", s.cfg.Timeout)
	}
	b.WriteString("\n--- stdout ---\n")
	b.Write(stdout.bytes())
	b.WriteString("\n--- stderr ---\n")
	b.Write(stderr.bytes())

	return &mcp.CallToolResult{
		IsError: exit != 0,
		Content: []mcp.Content{&mcp.TextContent{Text: b.String()}},
	}
}

// record appends the event to the flight log. A recorder failure is
// surfaced on the result — an unauditable proxy must not look healthy.
func (s *Server) record(ev recorder.Event, result *mcp.CallToolResult) *mcp.CallToolResult {
	if err := s.cfg.Rec.Record(ev); err != nil {
		result.IsError = true
		result.Content = append(result.Content, &mcp.TextContent{
			Text: fmt.Sprintf("WARNING: flight recorder write failed: %v", err),
		})
	}
	return result
}

// policyRuleLabel renders the decisive rule for the recorder (ADR-015).
func policyRuleLabel(res policy.Result) string {
	if res.ByDefault {
		if res.DefaultSource == "" {
			return "default:engine"
		}
		return "default:" + res.DefaultSource
	}
	return fmt.Sprintf("%s: %s", res.Rule.Source, res.Rule.Pattern)
}

// reasonSuffix renders the decisive rule's reason, if it has one.
func reasonSuffix(res policy.Result) string {
	if res.Rule == nil || res.Rule.Reason == "" {
		return ""
	}
	return " — " + res.Rule.Reason
}

// headSHA reads the repo's current HEAD; empty when unreadable. Re-read
// per event: implementer sessions commit mid-session (ADR-015).
func headSHA(repoRoot string) string {
	out, err := exec.Command("git", "-C", repoRoot, "rev-parse", "HEAD").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

// cappedBuffer keeps the first cap bytes and notes any overflow.
type cappedBuffer struct {
	buf       bytes.Buffer
	cap       int
	truncated bool
}

func (c *cappedBuffer) Write(p []byte) (int, error) {
	if room := c.cap - c.buf.Len(); room > 0 {
		if len(p) > room {
			c.buf.Write(p[:room])
			c.truncated = true
		} else {
			c.buf.Write(p)
		}
	} else if len(p) > 0 {
		c.truncated = true
	}
	return len(p), nil
}

func (c *cappedBuffer) bytes() []byte {
	if c.truncated {
		return append(c.buf.Bytes(), fmt.Sprintf("\n[truncated at %d KiB]", c.cap/1024)...)
	}
	return c.buf.Bytes()
}
