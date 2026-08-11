// Package knowledge answers the knowledge-layer queries (architecture
// §6, ADR-017) from a repo's derived artifacts: graph_neighborhood,
// who_calls, and tests_guarding over the extracted skeleton, and
// get_module_doc over the M5 narrative artifacts (ADR-019), read fresh
// from .hobbes/derived/ on every call. Answers are agent-facing text
// with file:line provenance and a visible staleness header (P1) — this
// package never writes.
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

// --- module docs (ADR-019 artifacts) ---------------------------------------

// claim is one pinned narrative sentence (ADR-019).
type claim struct {
	Text string     `json:"text"`
	Pins []evidence `json:"pins"`
}

func (c claim) cite() string {
	if len(c.Pins) == 0 {
		return ""
	}
	cites := make([]string, len(c.Pins))
	for i, p := range c.Pins {
		cites[i] = p.String()
	}
	return "  [" + strings.Join(cites, ", ") + "]"
}

// docSource is a blob-stamped file a narrative artifact cites.
type docSource struct {
	Path    string `json:"path"`
	BlobSHA string `json:"blob_sha"`
}

type moduleDoc struct {
	SHA              string      `json:"sha"`
	Dirty            bool        `json:"dirty"`
	ID               string      `json:"id"`
	Path             string      `json:"path"`
	Sources          []docSource `json:"sources"`
	Purpose          claim       `json:"purpose"`
	Responsibilities []claim     `json:"responsibilities"`
	Gotchas          []claim     `json:"gotchas"`
}

// ModuleDoc answers get_module_doc(node): the narrative doc for one
// module — purpose, responsibilities, gotchas, every claim pinned. The
// stale warning is blob-level (ADR-019), not the HEAD compare the
// skeleton tools use: docs regenerate per cited file, so HEAD moving
// on its own proves nothing about this doc.
func (s *Store) ModuleDoc(nodeID string) (string, error) {
	if nodeID != filepath.Base(nodeID) || strings.Contains(nodeID, "..") {
		return "", fmt.Errorf("%q is not a module id", nodeID)
	}
	dir := filepath.Join(s.repoRoot, ".hobbes", "derived", "docs", "modules")
	data, err := os.ReadFile(filepath.Join(dir, nodeID+".json"))
	if os.IsNotExist(err) {
		ids := docIDs(dir)
		if len(ids) == 0 {
			return "", fmt.Errorf("no module docs generated — run `hobbes narrate` first")
		}
		return fmt.Sprintf("no module doc for %q\n%s", nodeID, suggest(nodeID, ids)), nil
	}
	if err != nil {
		return "", err
	}
	var d moduleDoc
	if err := json.Unmarshal(data, &d); err != nil {
		return "", fmt.Errorf("module doc %s: %w", nodeID, err)
	}

	var b strings.Builder
	fmt.Fprintf(&b, "knowledge from narrate @ %.12s", d.SHA)
	if d.Dirty {
		b.WriteString(" (dirty tree)")
	}
	b.WriteString("\n")
	if changed := s.changedSources(d.Sources); len(changed) > 0 {
		fmt.Fprintf(&b,
			"WARNING: STALE — cited files changed since generation: %s; rerun `hobbes narrate`\n",
			strings.Join(changed, ", "))
	}
	fmt.Fprintf(&b, "module %s (%s)\n", d.ID, d.Path)
	fmt.Fprintf(&b, "purpose: %s%s\n", d.Purpose.Text, d.Purpose.cite())
	for _, section := range []struct {
		title  string
		claims []claim
	}{{"responsibilities", d.Responsibilities}, {"gotchas", d.Gotchas}} {
		if len(section.claims) == 0 {
			continue
		}
		b.WriteString(section.title + ":\n")
		for _, c := range section.claims {
			fmt.Fprintf(&b, "  - %s%s\n", c.Text, c.cite())
		}
	}
	return b.String(), nil
}

// docIDs lists the module ids with docs on disk, for near-miss answers.
func docIDs(dir string) []string {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	var ids []string
	for _, e := range entries {
		if name, ok := strings.CutSuffix(e.Name(), ".json"); ok && !e.IsDir() {
			ids = append(ids, name)
		}
	}
	return ids
}

// changedSources reports which stamped sources' working-tree blobs no
// longer match (ADR-019 staleness). A vanished file counts as changed;
// git being unavailable degrades to no warning, like gitHead.
func (s *Store) changedSources(sources []docSource) []string {
	changed := map[string]bool{}
	var existing []string
	for _, src := range sources {
		if _, err := os.Stat(filepath.Join(s.repoRoot, src.Path)); err != nil {
			changed[src.Path] = true
		} else {
			existing = append(existing, src.Path)
		}
	}
	if len(existing) > 0 {
		cmd := exec.Command("git", "-C", s.repoRoot, "hash-object", "--stdin-paths")
		cmd.Stdin = strings.NewReader(strings.Join(existing, "\n") + "\n")
		if out, err := cmd.Output(); err == nil {
			hashes := strings.Fields(string(out))
			if len(hashes) == len(existing) {
				current := make(map[string]string, len(existing))
				for i, p := range existing {
					current[p] = hashes[i]
				}
				for _, src := range sources {
					if h, ok := current[src.Path]; ok && h != src.BlobSHA {
						changed[src.Path] = true
					}
				}
			}
		}
	}
	out := make([]string, 0, len(changed))
	for p := range changed {
		out = append(out, p)
	}
	sort.Strings(out)
	return out
}
