// Package knowledge answers the v1 knowledge-layer queries (architecture
// §6, ADR-017) from a repo's derived artifacts: graph_neighborhood,
// who_calls, and tests_guarding, read fresh from .hobbes/derived/ on
// every call. Answers are agent-facing text with file:line provenance
// and a visible staleness header (P1) — this package never writes.
package knowledge

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
)

// Store reads one repo's derived artifacts.
type Store struct {
	repoRoot string
}

// Open returns a Store for the repo. No I/O happens until a query.
func Open(repoRoot string) *Store { return &Store{repoRoot: repoRoot} }

// evidence is a file:line citation on an edge.
type evidence struct {
	Path string `json:"path"`
	Line int    `json:"line"`
}

func (e evidence) String() string { return fmt.Sprintf("%s:%d", e.Path, e.Line) }

type edge struct {
	From     string     `json:"from"`
	To       string     `json:"to"`
	Type     string     `json:"type"`
	Evidence []evidence `json:"evidence"`
}

func (e edge) cite() string {
	if len(e.Evidence) == 0 {
		return ""
	}
	cites := make([]string, len(e.Evidence))
	for i, ev := range e.Evidence {
		cites[i] = ev.String()
	}
	return "  [" + strings.Join(cites, ", ") + "]"
}

type node struct {
	ID   string `json:"id"`
	Kind string `json:"kind"`
	Path string `json:"path"`
}

type symbol struct {
	ID     string `json:"id"`
	Module string `json:"module"`
	Kind   string `json:"kind"`
	Line   int    `json:"line"`
}

type graphDoc struct {
	SHA         string   `json:"sha"`
	Dirty       bool     `json:"dirty"`
	Nodes       []node   `json:"nodes"`
	ModuleEdges []edge   `json:"module_edges"`
	Symbols     []symbol `json:"symbols"`
	SymbolEdges []edge   `json:"symbol_edges"`
}

type test struct {
	ID             string   `json:"id"`
	File           string   `json:"file"`
	Line           int      `json:"line"`
	Reaches        []string `json:"reaches"`
	ReachesModules []string `json:"reaches_modules"`
}

type testsDoc struct {
	SHA   string `json:"sha"`
	Dirty bool   `json:"dirty"`
	Tests []test `json:"tests"`
}

// loadInto reads one derived artifact; a missing file is the one error
// agents can fix themselves, so say how.
func (s *Store) loadInto(name string, v any) error {
	path := filepath.Join(s.repoRoot, ".hobbes", "derived", name)
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return fmt.Errorf("%s not found — run `hobbes ingest` first", path)
	}
	if err != nil {
		return err
	}
	if err := json.Unmarshal(data, v); err != nil {
		return fmt.Errorf("%s: %w", path, err)
	}
	return nil
}

// header renders the provenance line every answer starts with, plus a
// stale warning when the repo has moved past the ingest (P1: staleness
// is visible, never silent).
func (s *Store) header(sha string, dirty bool) string {
	h := fmt.Sprintf("knowledge from ingest @ %.12s", sha)
	if dirty {
		h += " (dirty tree)"
	}
	if head := gitHead(s.repoRoot); head != "" && head != sha {
		h += fmt.Sprintf("\nWARNING: repo HEAD is %.12s — artifacts are stale; rerun `hobbes ingest`", head)
	}
	return h + "\n"
}

func gitHead(repoRoot string) string {
	out, err := exec.Command("git", "-C", repoRoot, "rev-parse", "HEAD").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

// suggest lists ids containing the query, for near-miss answers.
func suggest(query string, ids []string) string {
	q := strings.ToLower(query)
	var hits []string
	for _, id := range ids {
		if strings.Contains(strings.ToLower(id), q) {
			hits = append(hits, id)
		}
	}
	sort.Strings(hits)
	if len(hits) == 0 {
		return ""
	}
	if len(hits) > 10 {
		hits = hits[:10]
	}
	return "did you mean:\n  " + strings.Join(hits, "\n  ") + "\n"
}

// Neighborhood answers graph_neighborhood(node): the node's kind, then
// every module edge in and out, with types and provenance.
func (s *Store) Neighborhood(nodeID string) (string, error) {
	var g graphDoc
	if err := s.loadInto("graph.json", &g); err != nil {
		return "", err
	}
	var b strings.Builder
	b.WriteString(s.header(g.SHA, g.Dirty))

	var found *node
	ids := make([]string, len(g.Nodes))
	for i := range g.Nodes {
		ids[i] = g.Nodes[i].ID
		if g.Nodes[i].ID == nodeID {
			found = &g.Nodes[i]
		}
	}
	if found == nil {
		b.WriteString(fmt.Sprintf("no node %q in the graph\n", nodeID))
		b.WriteString(suggest(nodeID, ids))
		return b.String(), nil
	}

	b.WriteString(fmt.Sprintf("%s (%s", found.ID, found.Kind))
	if found.Path != "" {
		b.WriteString(", " + found.Path)
	}
	b.WriteString(")\n")

	out, in := 0, 0
	for _, e := range g.ModuleEdges {
		if e.From == nodeID {
			if out == 0 {
				b.WriteString("outgoing:\n")
			}
			out++
			b.WriteString(fmt.Sprintf("  -%s-> %s%s\n", e.Type, e.To, e.cite()))
		}
	}
	for _, e := range g.ModuleEdges {
		if e.To == nodeID {
			if in == 0 {
				b.WriteString("incoming:\n")
			}
			in++
			b.WriteString(fmt.Sprintf("  <-%s- %s%s\n", e.Type, e.From, e.cite()))
		}
	}
	if out+in == 0 {
		b.WriteString("no module edges touch this node\n")
	}
	return b.String(), nil
}

// WhoCalls answers who_calls(symbol): every call edge into the symbol,
// with provenance.
func (s *Store) WhoCalls(symbolID string) (string, error) {
	var g graphDoc
	if err := s.loadInto("graph.json", &g); err != nil {
		return "", err
	}
	var b strings.Builder
	b.WriteString(s.header(g.SHA, g.Dirty))

	callers := 0
	for _, e := range g.SymbolEdges {
		if e.To == symbolID {
			if callers == 0 {
				b.WriteString(fmt.Sprintf("callers of %s:\n", symbolID))
			}
			callers++
			b.WriteString(fmt.Sprintf("  %s%s\n", e.From, e.cite()))
		}
	}
	if callers > 0 {
		return b.String(), nil
	}

	ids := make([]string, len(g.Symbols))
	known := false
	for i, sym := range g.Symbols {
		ids[i] = sym.ID
		known = known || sym.ID == symbolID
	}
	if known {
		b.WriteString(fmt.Sprintf("no recorded callers of %s (static call edges only — dynamic dispatch is not traced)\n", symbolID))
	} else {
		b.WriteString(fmt.Sprintf("no symbol %q in the graph\n", symbolID))
		b.WriteString(suggest(symbolID, ids))
	}
	return b.String(), nil
}

// TestsGuarding answers tests_guarding(target), where target is a module
// id or a path (file or directory prefix): the tests that statically
// reach it.
func (s *Store) TestsGuarding(target string) (string, error) {
	var g graphDoc
	if err := s.loadInto("graph.json", &g); err != nil {
		return "", err
	}
	var t testsDoc
	if err := s.loadInto("tests.json", &t); err != nil {
		return "", err
	}
	var b strings.Builder
	b.WriteString(s.header(t.SHA, t.Dirty))

	// Resolve target to a set of module ids: an exact module id, or the
	// modules whose source path sits under a path-ish target.
	modules := map[string]bool{}
	var moduleIDs []string
	for _, n := range g.Nodes {
		if n.Kind != "module" {
			continue
		}
		moduleIDs = append(moduleIDs, n.ID)
		if n.ID == target {
			modules[n.ID] = true
		} else if n.Path == target || strings.HasPrefix(n.Path, strings.TrimSuffix(target, "/")+"/") {
			modules[n.ID] = true
		}
	}
	if len(modules) == 0 {
		b.WriteString(fmt.Sprintf("no module matches %q (give a module id or a repo-relative path)\n", target))
		b.WriteString(suggest(target, moduleIDs))
		return b.String(), nil
	}

	guarded := 0
	for _, tc := range t.Tests {
		hit := false
		for _, m := range tc.ReachesModules {
			if modules[m] {
				hit = true
				break
			}
		}
		if !hit {
			continue
		}
		if guarded == 0 {
			b.WriteString(fmt.Sprintf("tests statically reaching %s:\n", target))
		}
		guarded++
		b.WriteString(fmt.Sprintf("  %s  [%s:%d]\n", tc.ID, tc.File, tc.Line))
	}
	if guarded == 0 {
		b.WriteString(fmt.Sprintf("no tests statically reach %s — changes there are unguarded\n", target))
	}
	return b.String(), nil
}
