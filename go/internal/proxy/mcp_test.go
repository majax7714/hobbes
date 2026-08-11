package proxy

// Protocol-level tests: a real MCP client and server wired over the SDK's
// in-memory transport pair — the same code path Claude Code exercises over
// stdio (ADR-013), minus the pipes.

import (
	"context"
	"strings"
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

func connect(t *testing.T, s *Server) *mcp.ClientSession {
	t.Helper()
	ctx := context.Background()
	clientT, serverT := mcp.NewInMemoryTransports()
	if _, err := s.MCP().Connect(ctx, serverT, nil); err != nil {
		t.Fatal(err)
	}
	client := mcp.NewClient(&mcp.Implementation{Name: "test-client", Version: "0.0.0"}, nil)
	session, err := client.Connect(ctx, clientT, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { session.Close() })
	return session
}

func TestExecToolIsListed(t *testing.T) {
	s, _ := newServer(t, testRepo(t), 0)
	session := connect(t, s)
	tools, err := session.ListTools(context.Background(), nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(tools.Tools) != 1 || tools.Tools[0].Name != "exec" {
		t.Fatalf("tools = %+v, want exactly [exec]", tools.Tools)
	}
	if !strings.Contains(tools.Tools[0].Description, "policy") {
		t.Error("exec description should warn the agent about policy gating")
	}
}

func TestRoundTripAllowAndDenyAreLogged(t *testing.T) {
	s, logPath := newServer(t, testRepo(t), 0)
	session := connect(t, s)
	ctx := context.Background()

	allowed, err := session.CallTool(ctx, &mcp.CallToolParams{
		Name:      "exec",
		Arguments: map[string]any{"command": "echo over-the-wire"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if allowed.IsError || !strings.Contains(text(allowed), "over-the-wire") {
		t.Errorf("allowed call: isError=%v text=%q", allowed.IsError, text(allowed))
	}

	denied, err := session.CallTool(ctx, &mcp.CallToolParams{
		Name:      "exec",
		Arguments: map[string]any{"command": "rm -rf /"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if !denied.IsError || !strings.Contains(text(denied), "policy denied") {
		t.Errorf("denied call: isError=%v text=%q", denied.IsError, text(denied))
	}

	evs := events(t, logPath)
	if len(evs) != 2 || evs[0].Decision != "allow" || evs[1].Decision != "deny" {
		t.Fatalf("flight log = %+v, want allow then deny", evs)
	}
}
