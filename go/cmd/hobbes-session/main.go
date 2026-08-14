// Command hobbes-session launches an agent session in a rootless Podman
// sandbox (M4, ADR-018): a fresh git worktree, the merged policy mapped to
// mounts, a clean environment, and Claude Code wired to the hobbes-proxy
// MCP server. It creates the worktree, writes the MCP config, runs
// `podman run`, and removes the worktree on exit.
//
// Usage:
//
//	hobbes-session start --repo DIR --role ROLE [--task "..."] [flags]
//	  [--dry-run] [--image IMG] [--network NET] [--claude-cred]
//	  [-- CMD ARGS...]   # override the in-container command (exit check)
//
// Exit codes: the session command's code · 1 setup error · 2 usage.
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	"github.com/majax7714/hobbes/go/internal/sandbox"
)

const (
	exitError = 1
	exitUsage = 2
)

const usage = `usage: hobbes-session start --repo DIR --role ROLE [flags] [-- CMD...]

Launch an agent session in a rootless Podman sandbox: a fresh git worktree
mounted rw, the hobbes-proxy MCP server enforcing policy, and a clean
environment. Without a trailing command, runs Claude Code as the session's
implementer.

flags:
  --repo DIR       repo to spawn a session from (required)
  --role ROLE      session role (required)
  --task TEXT      the implementer's prompt (default Claude Code command)
  --session ID     session id (default: generated)
  --image IMG      session image (default hobbes-session:local)
  --network NET    podman --network (default none)
  --box FILE       box policy (default ~/.hobbes/box.policy if present)
  --proxy-bin FILE static hobbes-proxy binary to mount (default: next to me)
  --sessions DIR   session-state root (default ~/.hobbes/sessions)
  --claude-cred    mount ~/.claude ro (needed for a live Claude Code run)
  --dry-run        print the podman argv and MCP config, run nothing
  -- CMD...        run CMD in the sandbox instead of Claude Code
`

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}

func run(args []string, stdout, stderr io.Writer) int {
	if len(args) == 0 {
		fmt.Fprint(stderr, usage)
		return exitUsage
	}
	switch args[0] {
	case "start":
		return runStart(args[1:], stdout, stderr)
	case "help", "-h", "--help":
		fmt.Fprint(stderr, usage)
		return 0
	default:
		fmt.Fprintf(stderr, "hobbes-session: unknown command %q\n\n%s", args[0], usage)
		return exitUsage
	}
}

// options holds parsed start flags plus the trailing command override.
type options struct {
	repo, role, task, session string
	image, network, box       string
	proxyBin, sessions        string
	claudeCred, dryRun        bool
	command                   []string
}

func runStart(args []string, stdout, stderr io.Writer) int {
	opt, code := parseStart(args, stderr)
	if code != 0 {
		return code
	}

	plan, worktree, cleanup, err := setup(opt)
	if err != nil {
		fmt.Fprintf(stderr, "hobbes-session: %v\n", err)
		return exitError
	}
	defer cleanup()

	if opt.dryRun {
		fmt.Fprint(stdout, plan.DryRun())
		return 0
	}

	fmt.Fprintf(stderr, "hobbes-session: %s (role %s)\n  worktree %s\n  flight log %s\n",
		plan.SessionID(), opt.role, worktree,
		filepath.Join(opt.sessions, plan.SessionID(), "flight.jsonl"))

	cmd := exec.Command("podman", plan.PodmanArgs()...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, stdout, stderr
	if err := cmd.Run(); err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			return ee.ExitCode()
		}
		fmt.Fprintf(stderr, "hobbes-session: podman: %v\n", err)
		return exitError
	}
	return 0
}

// setup creates the worktree and session dir, writes the MCP config, and
// returns the plan plus a teardown that removes the worktree.
func setup(opt options) (*sandbox.Plan, string, func(), error) {
	noop := func() {}

	repo, err := filepath.Abs(opt.repo)
	if err != nil {
		return nil, "", noop, err
	}
	if info, err := os.Stat(filepath.Join(repo, ".git")); err != nil || !info.IsDir() {
		return nil, "", noop, fmt.Errorf("%s is not a git repo (no .git dir)", repo)
	}

	sessionDir := filepath.Join(opt.sessions, opt.session)
	worktree := filepath.Join(sessionDir, "worktree")
	if err := os.MkdirAll(sessionDir, 0o700); err != nil {
		return nil, "", noop, err
	}

	// A fresh, self-contained local clone on a session branch (§6:
	// sessions never share a tree). A clone rather than a linked worktree
	// because the container mounts only /work — a worktree's .git points
	// back into the canonical repo's gitdir, which is deliberately not
	// mounted; a `--local` clone copies the object store into the session
	// dir and so needs no path outside /work, which is what lets git work
	// inside the sandbox while the canonical repo stays unreachable from
	// the container (ADR-018).
	//
	// `--no-hardlinks` because a local clone hardlinks objects by default,
	// and a hardlink cannot cross a filesystem: with the repo and the
	// sessions dir (under $HOME) on different devices, the clone died with
	// "Invalid cross-device link", which names the symptom and not the
	// cause. The cost is a real copy of the object store; the benefit is
	// that a repo on a mounted volume or a ramdisk checkout works at all.
	if out, err := gitOut(repo, "clone", "--local", "--no-hardlinks", "--quiet", repo, worktree); err != nil {
		return nil, "", noop, fmt.Errorf("git clone: %v: %s", err, out)
	}
	if out, err := gitOut(worktree, "checkout", "-q", "-b", "hobbes/"+opt.session); err != nil {
		os.RemoveAll(worktree)
		return nil, "", noop, fmt.Errorf("git checkout: %v: %s", err, out)
	}
	// Seed the session's knowledge layer: derived artifacts are gitignored
	// (ADR-012), so the clone lacks them; copy the box's current ingest in
	// so the knowledge tools (ADR-017) have data to answer from.
	seedDerived(repo, worktree)
	cleanup := func() {
		// Only the clone is disposable; the flight log and escalation
		// records under sessionDir are the audit trail and stay.
		os.RemoveAll(worktree)
	}

	plan, err := sandbox.NewPlan(sandbox.Config{
		SessionID:    opt.session,
		Role:         opt.role,
		Image:        opt.image,
		Task:         opt.task,
		Network:      opt.network,
		HostWorktree: worktree,
		HostSessions: opt.sessions,
		HostProxyBin: opt.proxyBin,
		HostBoxPath:  opt.box,
		HostClaude:   claudeMount(opt.claudeCred),
		HostDerived:  derivedMount(opt.repo),
		Command:      opt.command,
	})
	if err != nil {
		cleanup()
		return nil, "", noop, err
	}

	if err := os.WriteFile(plan.MCPConfigHostPath(), []byte(plan.MCPConfig()), 0o600); err != nil {
		cleanup()
		return nil, "", noop, err
	}
	return plan, worktree, cleanup, nil
}

func gitOut(repo string, args ...string) (string, error) {
	out, err := exec.Command("git", append([]string{"-C", repo}, args...)...).CombinedOutput()
	return string(out), err
}

// seedDerived copies the source repo's derived artifacts into the fresh
// clone, which lacks them (they are gitignored, ADR-012), so the session's
// knowledge tools have data. Best effort: a session with no ingest simply
// gets "run hobbes ingest" answers.
func seedDerived(repo, worktree string) {
	src := filepath.Join(repo, ".hobbes", "derived")
	if info, err := os.Stat(src); err != nil || !info.IsDir() {
		return
	}
	dst := filepath.Join(worktree, ".hobbes", "derived")
	_ = os.MkdirAll(dst, 0o755)
	entries, err := os.ReadDir(src)
	if err != nil {
		return
	}
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		data, err := os.ReadFile(filepath.Join(src, e.Name()))
		if err != nil {
			continue
		}
		_ = os.WriteFile(filepath.Join(dst, e.Name()), data, 0o644)
	}
}

// derivedMount is the host repo's .hobbes/derived when it exists. A
// session's worktree is a fresh checkout and derived/ is gitignored, so
// without this the knowledge tools have nothing to read and a reviewer
// starts blind — the opposite of §6's "oriented via MCP, not cold grep".
// Absent artifacts are not an error: the tools already answer "run
// hobbes ingest".
func derivedMount(repo string) string {
	path := filepath.Join(repo, ".hobbes", "derived")
	if info, err := os.Stat(path); err != nil || !info.IsDir() {
		return ""
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return ""
	}
	return abs
}

func claudeMount(want bool) string {
	if !want {
		return ""
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".claude")
}

// parseStart handles flags and the "--" command override. Returns a
// non-zero code (and prints) on any flag trouble.
func parseStart(args []string, stderr io.Writer) (options, int) {
	var opt options
	// Split off a trailing "-- CMD..." before flag parsing.
	flags := args
	for i, a := range args {
		if a == "--" {
			flags = args[:i]
			opt.command = args[i+1:]
			break
		}
	}

	home, _ := os.UserHomeDir()
	fs := newFlagSet(stderr)
	fs.StringVar(&opt.repo, "repo", "", "")
	fs.StringVar(&opt.role, "role", "", "")
	fs.StringVar(&opt.task, "task", "", "")
	fs.StringVar(&opt.session, "session", "", "")
	fs.StringVar(&opt.image, "image", "", "")
	fs.StringVar(&opt.network, "network", "", "")
	fs.StringVar(&opt.box, "box", "", "")
	fs.StringVar(&opt.proxyBin, "proxy-bin", "", "")
	fs.StringVar(&opt.sessions, "sessions", "", "")
	fs.BoolVar(&opt.claudeCred, "claude-cred", false, "")
	fs.BoolVar(&opt.dryRun, "dry-run", false, "")
	if err := fs.Parse(flags); err != nil {
		return opt, exitUsage
	}
	if opt.repo == "" || opt.role == "" {
		fmt.Fprintf(stderr, "hobbes-session start: --repo and --role are required\n\n%s", usage)
		return opt, exitUsage
	}

	if opt.sessions == "" {
		if home == "" {
			fmt.Fprintln(stderr, "hobbes-session start: no home dir; pass --sessions")
			return opt, exitError
		}
		opt.sessions = filepath.Join(home, ".hobbes", "sessions")
	}
	if opt.session == "" {
		id, err := sandbox.NewID(time.Now())
		if err != nil {
			fmt.Fprintf(stderr, "hobbes-session start: %v\n", err)
			return opt, exitError
		}
		opt.session = id
	}
	if opt.box == "" && home != "" {
		if def := filepath.Join(home, ".hobbes", "box.policy"); fileExists(def) {
			opt.box = def
		}
	}
	if opt.proxyBin == "" {
		opt.proxyBin = defaultProxyBin()
	}
	if opt.proxyBin == "" || !fileExists(opt.proxyBin) {
		fmt.Fprintf(stderr, "hobbes-session start: proxy binary %q not found; pass --proxy-bin\n", opt.proxyBin)
		return opt, exitError
	}
	return opt, 0
}

// defaultProxyBin looks for hobbes-proxy next to this binary.
func defaultProxyBin() string {
	self, err := os.Executable()
	if err != nil {
		return ""
	}
	cand := filepath.Join(filepath.Dir(self), "hobbes-proxy")
	if fileExists(cand) {
		return cand
	}
	return ""
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

// newFlagSet builds the start flag set (help text lives in the usage
// string, so the flags themselves stay terse).
func newFlagSet(stderr io.Writer) *flag.FlagSet {
	fs := flag.NewFlagSet("start", flag.ContinueOnError)
	fs.SetOutput(stderr)
	return fs
}
