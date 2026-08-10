# web/ — human surface

The four-tab web UI (Graph · Tests · Docs · Diff, plus Sessions) described in
architecture §7. Intentionally empty until **M7**, per the build plan's
"content before chrome" sequencing rule — the UI comes after there is a
knowledge layer worth rendering.

When scaffolded (M7): Vite + React + TypeScript, interactive graph via
**Cytoscape.js** (locked decision D3; Mermaid remains the markdown/export
renderer).
