package policy

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Locations of policy files relative to their scope root (ADR-001).
const (
	// RepoPolicyRel is the repo policy path relative to the repo root.
	RepoPolicyRel = ".hobbes/policies/repo.policy"
	// FolderPolicyRel is the folder policy path relative to any directory
	// inside the repo.
	FolderPolicyRel = ".hobbes/folder.policy"
)

// Chain is an ordered set of policy files, least specific first:
// box, repo, then folder policies from the repo root down to the working
// directory. Resolve applies ADR-002 semantics over this order.
type Chain struct {
	Files []*File
}

// LoadChain assembles the policy chain for a command running in dir, which
// must be inside repoRoot (repoRoot itself is allowed).
//
// boxPath, if non-empty, must name an existing box policy — the caller
// decides whether a missing box policy is an error (an explicitly configured
// path) or skippable (the ~/.hobbes/box.policy default; see ADR-003). The
// repo policy and folder policies are loaded only where present: every
// directory from repoRoot down to dir contributes its folder.policy, deepest
// last, so deeper folders are more specific.
//
// Any file whose declared scope disagrees with the level it is loaded at is
// an error.
func LoadChain(boxPath, repoRoot, dir string) (*Chain, error) {
	var chain Chain

	add := func(path, level string) error {
		f, err := LoadFile(path)
		if err != nil {
			return err
		}
		if f.Scope != "" && f.Scope != level {
			return fmt.Errorf("%s: declared scope %q but loaded as %s policy", path, f.Scope, level)
		}
		f.Level = level
		chain.Files = append(chain.Files, f)
		return nil
	}

	if boxPath != "" {
		if err := add(boxPath, "box"); err != nil {
			return nil, err
		}
	}

	repoRoot, err := filepath.Abs(repoRoot)
	if err != nil {
		return nil, err
	}
	dir, err = filepath.Abs(dir)
	if err != nil {
		return nil, err
	}
	rel, err := filepath.Rel(repoRoot, dir)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return nil, fmt.Errorf("directory %s is not inside repo %s", dir, repoRoot)
	}

	if p := filepath.Join(repoRoot, filepath.FromSlash(RepoPolicyRel)); fileExists(p) {
		if err := add(p, "repo"); err != nil {
			return nil, err
		}
	}

	// Walk repoRoot → dir, collecting folder policies shallowest first.
	current := repoRoot
	parts := []string{}
	if rel != "." {
		parts = strings.Split(rel, string(filepath.Separator))
	}
	for i := 0; i <= len(parts); i++ {
		if i > 0 {
			current = filepath.Join(current, parts[i-1])
		}
		if p := filepath.Join(current, filepath.FromSlash(FolderPolicyRel)); fileExists(p) {
			if err := add(p, "folder"); err != nil {
				return nil, err
			}
		}
	}

	return &chain, nil
}

// fileExists reports whether path exists and is a regular file.
func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}
