// Command hobbes-proxy is the per-session tool proxy daemon (M4, ADR-014):
// an MCP server over stdio that exposes one tool, exec, gated by the merged
// Hobbes policy chain and logged to the session's flight recorder. The
// session wrapper lists it in the sandboxed Claude Code's MCP config; one
// proxy process serves one session and dies with it.
//
// Usage:
//
//	hobbes-proxy serve --repo DIR --role ROLE [--session ID] [--box FILE]
//	                   [--log-dir DIR] [--timeout DUR]
//
// stdout carries the MCP protocol; all diagnostics go to stderr.
// Exit codes: 0 clean shutdown · 1 runtime error · 2 usage.
package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/majax7714/hobbes/go/internal/proxy"
	"github.com/majax7714/hobbes/go/internal/recorder"
)

const (
	exitOK    = 0
	exitError = 1
	exitUsage = 2
)

const usage = `usage: hobbes-proxy serve --repo DIR --role ROLE [flags]

Serve the Hobbes tool proxy for one agent session: an MCP server on stdio
exposing exec, policy-checked (allow | deny | escalate) and logged to the
session flight recorder (~/.hobbes/sessions/<session>/flight.jsonl).

flags:
  --repo DIR      repo root the session works in (required)
  --role ROLE     session role for policy and the audit trail (required)
  --session ID    session id (default: generated S-<utc>-<rand>)
  --box FILE      box policy (default: ~/.hobbes/box.policy if present)
  --log-dir DIR   flight-log root (default: ~/.hobbes/sessions)
  --timeout DUR   per-command wall clock (default 10m)
`

func main() {
	os.Exit(run(os.Args[1:], os.Stderr))
}

// run dispatches subcommands. Split from main for testability.
func run(args []string, stderr io.Writer) int {
	if len(args) == 0 {
		fmt.Fprint(stderr, usage)
		return exitUsage
	}
	switch args[0] {
	case "serve":
		return runServe(args[1:], stderr)
	case "help", "-h", "--help":
		fmt.Fprint(stderr, usage)
		return exitOK
	default:
		fmt.Fprintf(stderr, "hobbes-proxy: unknown command %q\n\n%s", args[0], usage)
		return exitUsage
	}
}

// runServe validates flags, opens the recorder, and serves MCP on stdio.
func runServe(args []string, stderr io.Writer) int {
	cfg, logPath, err := parseServe(args, stderr)
	if err != nil {
		if errors.Is(err, flag.ErrHelp) || errors.Is(err, errUsage) {
			return exitUsage
		}
		fmt.Fprintf(stderr, "hobbes-proxy serve: %v\n", err)
		return exitError
	}

	rec, err := recorder.Open(logPath)
	if err != nil {
		fmt.Fprintf(stderr, "hobbes-proxy serve: %v\n", err)
		return exitError
	}
	defer rec.Close()
	cfg.Rec = rec

	server, err := proxy.New(cfg)
	if err != nil {
		fmt.Fprintf(stderr, "hobbes-proxy serve: %v\n", err)
		return exitError
	}

	fmt.Fprintf(stderr, "hobbes-proxy: session %s role %s repo %s\nhobbes-proxy: flight log %s\n",
		cfg.Session, cfg.Role, cfg.RepoRoot, logPath)
	if err := server.MCP().Run(context.Background(), &mcp.StdioTransport{}); err != nil {
		fmt.Fprintf(stderr, "hobbes-proxy serve: %v\n", err)
		return exitError
	}
	return exitOK
}

// errUsage marks flag-validation failures whose message is already printed.
var errUsage = errors.New("usage")

// parseServe turns serve flags into a proxy config and flight-log path.
func parseServe(args []string, stderr io.Writer) (proxy.Config, string, error) {
	fs := flag.NewFlagSet("serve", flag.ContinueOnError)
	fs.SetOutput(stderr)
	repoFlag := fs.String("repo", "", "repo root (required)")
	roleFlag := fs.String("role", "", "session role (required)")
	sessionFlag := fs.String("session", "", "session id (default: generated)")
	boxFlag := fs.String("box", "", "box policy path")
	logDirFlag := fs.String("log-dir", "", "flight-log root (default: ~/.hobbes/sessions)")
	timeoutFlag := fs.Duration("timeout", proxy.DefaultTimeout, "per-command wall clock")
	if err := fs.Parse(args); err != nil {
		return proxy.Config{}, "", errUsage
	}

	if *repoFlag == "" || *roleFlag == "" {
		fmt.Fprintf(stderr, "hobbes-proxy serve: --repo and --role are required\n\n%s", usage)
		return proxy.Config{}, "", errUsage
	}
	repoRoot, err := filepath.Abs(*repoFlag)
	if err != nil {
		return proxy.Config{}, "", err
	}
	if info, err := os.Stat(repoRoot); err != nil || !info.IsDir() {
		return proxy.Config{}, "", fmt.Errorf("repo root %s is not a directory", repoRoot)
	}

	boxPath, err := resolveBoxPath(*boxFlag)
	if err != nil {
		return proxy.Config{}, "", err
	}

	session := *sessionFlag
	if session == "" {
		session, err = generateSessionID()
		if err != nil {
			return proxy.Config{}, "", err
		}
	}

	logDir := *logDirFlag
	if logDir == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return proxy.Config{}, "", fmt.Errorf("no home directory for the default --log-dir: %w", err)
		}
		logDir = filepath.Join(home, ".hobbes", "sessions")
	}

	cfg := proxy.Config{
		Session:  session,
		Role:     *roleFlag,
		RepoRoot: repoRoot,
		BoxPath:  boxPath,
		Timeout:  *timeoutFlag,
	}
	return cfg, filepath.Join(logDir, session, "flight.jsonl"), nil
}

// generateSessionID makes a sortable, collision-safe id (ADR-014).
func generateSessionID() (string, error) {
	var b [2]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	return fmt.Sprintf("S-%s-%s",
		time.Now().UTC().Format("20060102T150405Z"), hex.EncodeToString(b[:])), nil
}

// resolveBoxPath applies ADR-003's box policy rules (mirrors
// hobbes-policy): an explicit path must exist; the ~/.hobbes/box.policy
// default is skipped when absent.
func resolveBoxPath(flagValue string) (string, error) {
	if flagValue != "" {
		if _, err := os.Stat(flagValue); err != nil {
			return "", fmt.Errorf("box policy %s: %w", flagValue, err)
		}
		return flagValue, nil
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", nil // no home, no default box policy
	}
	def := filepath.Join(home, ".hobbes", "box.policy")
	if _, err := os.Stat(def); errors.Is(err, os.ErrNotExist) {
		return "", nil
	}
	return def, nil
}
