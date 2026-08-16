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
	"path"
	"path/filepath"
	"slices"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"

	"github.com/majax7714/hobbes/go/internal/derived"
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
	Tier     string     `json:"tier"`
	Evidence []evidence `json:"evidence"`
}

// qualify marks an edge the reader should trust less. Tier is the graph's
// trust signal (architecture §3.4): a `syntactic` edge is lane A's own
// resolution, kept because the semantic provider could not resolve the
// site and labelled because it can be wrong. An empty tier is a pre-v4
// artifact, which is not a guess and must not be styled as one.
func (e edge) qualify() string {
	if e.Tier == "syntactic" {
		return "  (syntactic — approximate)"
	}
	return ""
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
	// Version-check before decoding (ADR-028): these answers are cited at
	// agents with file:line, so a silently half-read graph would produce
	// confident wrong provenance. The tools read only fields present since
	// v3, so v4's additive tier/lane do not concern them.
	if err := derived.Unmarshal(name, data, derived.V3Compatible, v); err != nil {
		return err
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
// with provenance and tier.
//
// Filtered to type "calls" deliberately. Since V2.M2 the symbol layer also
// carries `uses` edges — a resolution no call site claimed: a type
// annotation, an `except` clause, a value passed by name (ADR-029). Those
// are true and useful and they are emphatically not calls, so counting
// them here would make a tool named who_calls answer who_references, which
// is the precise failure ADR-029 was written to avoid. It arrived anyway,
// through the new edge type rather than through a stripped lane, because
// no consumer filtered on type.
//
// They are reported under their own heading rather than dropped: an agent
// asking who calls this usually also wants to know who else names it, and
// silently discarding a true edge is its own kind of dishonesty (P8).
func (s *Store) WhoCalls(symbolID string) (string, error) {
	var g graphDoc
	if err := s.loadInto("graph.json", &g); err != nil {
		return "", err
	}
	var b strings.Builder
	b.WriteString(s.header(g.SHA, g.Dirty))

	callers, users := 0, 0
	var uses strings.Builder
	for _, e := range g.SymbolEdges {
		if e.To != symbolID {
			continue
		}
		switch e.Type {
		case "calls":
			if callers == 0 {
				b.WriteString(fmt.Sprintf("callers of %s:\n", symbolID))
			}
			callers++
			b.WriteString(fmt.Sprintf("  %s%s%s\n", e.From, e.cite(), e.qualify()))
		case "uses":
			users++
			uses.WriteString(fmt.Sprintf("  %s%s\n", e.From, e.cite()))
		}
	}
	if users > 0 {
		if callers == 0 {
			b.WriteString(fmt.Sprintf("no callers of %s\n", symbolID))
		}
		b.WriteString(fmt.Sprintf("references %s without calling it (type annotations, except clauses, values passed by name):\n", symbolID))
		b.WriteString(uses.String())
	}
	if callers > 0 || users > 0 {
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

// Source is a blob-stamped file a narrative artifact cites (ADR-019).
// Exported because the web surface (ADR-022) computes the same badge
// over the same stamps; staleness has one implementation.
type Source struct {
	Path    string `json:"path"`
	BlobSHA string `json:"blob_sha"`
}

type moduleDoc struct {
	SHA              string   `json:"sha"`
	Dirty            bool     `json:"dirty"`
	ID               string   `json:"id"`
	Path             string   `json:"path"`
	Sources          []Source `json:"sources"`
	Purpose          claim    `json:"purpose"`
	Responsibilities []claim  `json:"responsibilities"`
	Gotchas          []claim  `json:"gotchas"`
}

// ModuleDoc answers get_module_doc(node): the narrative doc for one
// module — purpose, responsibilities, gotchas, every claim pinned. The
// stale warning is blob-level (ADR-019), not the HEAD compare the
// skeleton tools use: docs regenerate per cited file, so HEAD moving
// on its own proves nothing about this doc.
func (s *Store) ModuleDoc(nodeID string) (string, error) {
	// TS/JS module ids are repo-relative paths (ADR-021), so "/" is
	// legal and artifacts nest under docs/modules/; traversal is not.
	if nodeID == "" || strings.HasPrefix(nodeID, "/") ||
		strings.Contains(nodeID, "\\") || path.Clean(nodeID) != nodeID ||
		slices.Contains(strings.Split(nodeID, "/"), "..") {
		return "", fmt.Errorf("%q is not a module id", nodeID)
	}
	dir := filepath.Join(s.repoRoot, ".hobbes", "derived", "docs", "modules")
	data, err := os.ReadFile(filepath.Join(dir, filepath.FromSlash(nodeID)+".json"))
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

// docIDs lists the module ids with docs on disk (nested dirs included,
// ADR-021), for near-miss answers.
func docIDs(dir string) []string {
	var ids []string
	_ = filepath.WalkDir(dir, func(p string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return nil
		}
		if rel, relErr := filepath.Rel(dir, p); relErr == nil {
			if name, ok := strings.CutSuffix(filepath.ToSlash(rel), ".json"); ok {
				ids = append(ids, name)
			}
		}
		return nil
	})
	return ids
}

// changedSources reports which of this store's stamped sources changed.
func (s *Store) changedSources(sources []Source) []string {
	return ChangedSources(s.repoRoot, sources)
}

// ChangedSources reports which stamped sources' working-tree blobs no
// longer match (ADR-019 staleness). A vanished file counts as changed;
// git being unavailable degrades to no warning, like gitHead.
func ChangedSources(repoRoot string, sources []Source) []string {
	return ChangedSourcesMulti(repoRoot, map[string][]Source{"": sources})[""]
}

// ChangedSourcesMulti answers ChangedSources for several artifacts at
// once, hashing the working tree in a single git call. The web surface's
// docs index (ADR-022) asks the badge question about every artifact on
// every load; one subprocess per artifact would be the whole cost of the
// endpoint.
func ChangedSourcesMulti(repoRoot string, bySources map[string][]Source) map[string][]string {
	// Hash every distinct existing path once, then answer per artifact.
	wanted := map[string]bool{}
	for _, sources := range bySources {
		for _, src := range sources {
			if _, err := os.Stat(filepath.Join(repoRoot, src.Path)); err == nil {
				wanted[src.Path] = true
			}
		}
	}
	existing := make([]string, 0, len(wanted))
	for p := range wanted {
		existing = append(existing, p)
	}
	sort.Strings(existing)

	current := map[string]string{}
	if len(existing) > 0 {
		cmd := exec.Command("git", "-C", repoRoot, "hash-object", "--stdin-paths")
		cmd.Stdin = strings.NewReader(strings.Join(existing, "\n") + "\n")
		if out, err := cmd.Output(); err == nil {
			if hashes := strings.Fields(string(out)); len(hashes) == len(existing) {
				for i, p := range existing {
					current[p] = hashes[i]
				}
			}
		}
	}

	result := make(map[string][]string, len(bySources))
	for id, sources := range bySources {
		changed := map[string]bool{}
		for _, src := range sources {
			if !wanted[src.Path] {
				changed[src.Path] = true // gone
				continue
			}
			// An unhashable tree (no git) leaves current empty: no badge,
			// same degradation as gitHead.
			if h, ok := current[src.Path]; ok && h != src.BlobSHA {
				changed[src.Path] = true
			}
		}
		out := make([]string, 0, len(changed))
		for p := range changed {
			out = append(out, p)
		}
		sort.Strings(out)
		result[id] = out
	}
	return result
}

// --- invariants (ADR-024) ---------------------------------------------------

// invariantRecord is one confirmed rule from .hobbes/invariants/. Only
// the fields an agent needs to obey it are read; the compile rule is the
// compiler's business, and its target is enough to say how it is checked.
type invariantRecord struct {
	ID        string   `yaml:"id"`
	Statement string   `yaml:"statement"`
	Scope     string   `yaml:"scope"`
	Status    string   `yaml:"status"`
	GuardedBy []string `yaml:"guarded_by"`
	// Check is how the record is held (graph | emit | soft, ADR-039);
	// Compile.Target names the CI tool for emit records.
	Check   string `yaml:"check"`
	Compile struct {
		Target string `yaml:"target"`
	} `yaml:"compile"`
}

// ListInvariants answers list_invariants(scope): the confirmed rules
// that bind a path, so a session knows the constraints before it writes
// code rather than after review (ADR-017's fifth tool, whose data
// arrived with M8).
//
// An empty scope lists everything. Scope matching is the ADR-024 rule: a
// record binds a path when its own scope contains that path, or the
// other way round — asking about the repo root should not hide a rule
// scoped to a subdirectory inside it.
func (s *Store) ListInvariants(scope string) (string, error) {
	dir := filepath.Join(s.repoRoot, ".hobbes", "invariants")
	entries, err := os.ReadDir(dir)
	if os.IsNotExist(err) {
		return "no invariants directory — none have been confirmed for this repo\n", nil
	}
	if err != nil {
		return "", err
	}

	var records []invariantRecord
	skipped := 0
	for _, entry := range entries {
		if entry.IsDir() || filepath.Ext(entry.Name()) != ".yaml" {
			continue
		}
		data, readErr := os.ReadFile(filepath.Join(dir, entry.Name()))
		if readErr != nil {
			continue
		}
		var record invariantRecord
		if yaml.Unmarshal(data, &record) != nil || record.ID == "" {
			continue
		}
		if record.Status != "confirmed" {
			skipped++
			continue
		}
		if scope != "" && !scopeOverlaps(record.Scope, scope) {
			continue
		}
		records = append(records, record)
	}
	sort.Slice(records, func(i, j int) bool { return records[i].ID < records[j].ID })

	var b strings.Builder
	if scope == "" {
		fmt.Fprintf(&b, "confirmed invariants (%d)\n", len(records))
	} else {
		fmt.Fprintf(&b, "confirmed invariants binding %s (%d)\n", scope, len(records))
	}
	if len(records) == 0 {
		b.WriteString("  none — nothing has been confirmed for this scope\n")
	}
	for _, record := range records {
		var how string
		switch record.Check {
		case "soft":
			how = "soft (a reviewer judges it; cite evidence)"
		case "graph":
			how = "graph (the unified checker judges it on every review)"
		case "emit":
			how = "emit:" + record.Compile.Target
		default:
			// A pre-ADR-039 record; show what it carries rather than
			// guessing what it meant.
			how = record.Compile.Target
			if how == "soft" {
				how = "soft (a reviewer judges it; cite evidence)"
			}
		}
		fmt.Fprintf(&b, "%s [scope %s, checked by %s]\n  %s\n",
			record.ID, record.Scope, how, record.Statement)
		if len(record.GuardedBy) > 0 {
			fmt.Fprintf(&b, "  guarded by: %s\n", strings.Join(record.GuardedBy, ", "))
		}
	}
	if skipped > 0 {
		fmt.Fprintf(&b, "(%d record(s) not confirmed, so not binding)\n", skipped)
	}
	return b.String(), nil
}

// scopeOverlaps reports whether a record's scope and a queried scope
// touch the same tree in either direction.
func scopeOverlaps(recordScope, query string) bool {
	record := strings.TrimSuffix(strings.TrimSpace(recordScope), "/")
	q := strings.TrimSuffix(strings.TrimSpace(query), "/")
	if record == "." || record == "" || q == "." || q == "" {
		return true
	}
	return record == q ||
		strings.HasPrefix(q, record+"/") ||
		strings.HasPrefix(record, q+"/")
}
