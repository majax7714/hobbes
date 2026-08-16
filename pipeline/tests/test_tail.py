"""The tail view (ADR-045): the unresolved remainder, classified by
observation.

Two properties matter more than any single class: every unresolved site
lands in exactly one class (per file the tail sums to the coverage
row's ``unresolved``), and nothing here infers — a class is a checkable
observation about the site or it is ``unclassified``. The integration
case runs the real extractor on the miniapp fixture with lane B off,
which is the suite's default and the degraded path P6 cares about: the
tail view must exist there too, not only when an indexer ran.
"""

from pathlib import Path

from hobbes.extract import evidence as ev
from hobbes.extract import extract_repo, tail

FIXTURE = Path(__file__).parent / "fixtures" / "miniapp"


def site(file, line, name, col=4):
    return ev.Site(ev.TREE_SITTER, ev.CALL_SITE, file, line, name, col)


def write(tmp_path, rel, text):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return rel


class TestClasses:
    def test_a_bare_builtin_named_call_is_builtin_name(self, tmp_path):
        f = write(tmp_path, "a.py", "x = 1\nn = len(items)\n")
        tails = tail.classify([site(f, 2, "len")], tmp_path)
        assert tails[f] == {tail.BUILTIN: 1}

    def test_builtin_names_are_per_language(self, tmp_path):
        # `len` is a Go builtin too; `isinstance` is not.
        f = write(tmp_path, "a.go", "n := len(items)\nisinstance(x)\n")
        tails = tail.classify(
            [site(f, 1, "len", col=9), site(f, 2, "isinstance", col=0)], tmp_path
        )
        assert tails[f][tail.BUILTIN] == 1
        assert tails[f][tail.UNCLASSIFIED] == 1

    def test_an_attribute_call_is_attr_call(self, tmp_path):
        f = write(tmp_path, "a.py", "out = capsys.readouterr()\n")
        tails = tail.classify([site(f, 1, "readouterr", col=13)], tmp_path)
        assert tails[f] == {tail.ATTR: 1}

    def test_optional_chaining_is_attr_call(self, tmp_path):
        f = write(tmp_path, "a.ts", "user?.refresh()\n")
        tails = tail.classify([site(f, 1, "refresh", col=6)], tmp_path)
        assert tails[f] == {tail.ATTR: 1}

    def test_a_path_qualified_call_is_path_call(self, tmp_path):
        f = write(tmp_path, "a.rs", "let x = Counter::new();\n")
        tails = tail.classify([site(f, 1, "new", col=17)], tmp_path)
        assert tails[f] == {tail.PATH_CALL: 1}

    def test_a_checker_origin_outranks_text_shape(self, tmp_path):
        # The checker knows setError is declared in this file; the text
        # shape (bare) never gets asked.
        f = write(tmp_path, "a.tsx", "setError(null)\n")
        origins = {(f, 1, "setError"): "local"}
        tails = tail.classify([site(f, 1, "setError", col=0)], tmp_path, origins=origins)
        assert tails[f] == {tail.LOCAL: 1}

    def test_each_checker_origin_maps_to_its_class(self, tmp_path):
        f = write(tmp_path, "a.ts", "a()\nb()\nc()\n")
        origins = {
            (f, 1, "a"): "local",
            (f, 2, "b"): "nested",
            (f, 3, "c"): "external",
        }
        sites = [site(f, n, x, col=0) for n, x in ((1, "a"), (2, "b"), (3, "c"))]
        tails = tail.classify(sites, tmp_path, origins=origins)
        assert tails[f] == {tail.LOCAL: 1, tail.NESTED: 1, tail.EXTERNAL_ORIGIN: 1}

    def test_a_fallback_resolved_site_outranks_everything(self, tmp_path):
        # Lane A produced a (syntactic) edge; the site is unresolved only
        # in the semantic ledger, and the class says exactly that.
        f = write(tmp_path, "a.py", "n = len(items)\n")
        fallback = {(f, 1, "len"): ("a.py", 1)}
        tails = tail.classify([site(f, 1, "len")], tmp_path, fallback=fallback)
        assert tails[f] == {tail.FALLBACK: 1}

    def test_an_unreadable_site_is_unclassified_never_guessed(self, tmp_path):
        missing = "gone.py"  # file absent: no observation, no class
        tails = tail.classify([site(missing, 1, "mystery")], tmp_path)
        assert tails[missing] == {tail.UNCLASSIFIED: 1}

    def test_a_name_absent_from_its_line_is_unclassified(self, tmp_path):
        # A wrapped chain can put the terminal on another line; without
        # the observation the site stays unclassified rather than shaped.
        f = write(tmp_path, "a.py", "something_else()\n")
        tails = tail.classify([site(f, 1, "refresh")], tmp_path)
        assert tails[f] == {tail.UNCLASSIFIED: 1}


class TestRollup:
    def test_rollup_groups_by_language_and_sums_tails(self):
        rows = [
            {"file": "a.py", "sites": 10, "unresolved": 2,
             "tail": {tail.BUILTIN: 2}},
            {"file": "b.py", "sites": 5, "unresolved": 1,
             "tail": {tail.ATTR: 1}},
            {"file": "c.go", "sites": 7, "unresolved": 0},
            {"file": "main.tf", "sites": 1, "unresolved": 1},  # no bucket
        ]
        langs = tail.rollup(rows)
        assert langs["python"]["sites"] == 15
        assert langs["python"]["tail"] == {tail.BUILTIN: 2, tail.ATTR: 1}
        assert langs["go"]["unresolved"] == 0
        assert "hcl" not in langs and None not in langs

    def test_not_modelled_covers_exactly_the_by_design_classes(self):
        assert tail.NOT_MODELLED == {tail.LOCAL, tail.NESTED, tail.BUILTIN}


class TestArtifact:
    def test_every_unresolved_site_is_classified_and_sums_match(self):
        # The degraded path (lane B off — the suite default): the tail
        # view exists, and per file its counts sum to `unresolved`.
        graph = extract_repo(FIXTURE).graph
        rows = graph["resolution_coverage"]
        assert rows, "fixture produced no coverage rows"
        for row in rows:
            if row["unresolved"]:
                assert sum(row["tail"].values()) == row["unresolved"], row
            else:
                assert "tail" not in row

    def test_the_fixture_tail_names_its_builtins(self):
        # miniapp's Python calls include builtin-named sites; with no
        # semantic lane the tail must still say so (pinned list, not
        # the running interpreter).
        graph = extract_repo(FIXTURE).graph
        classes = set()
        for row in graph["resolution_coverage"]:
            classes |= set(row.get("tail", {}))
        assert classes <= {
            tail.FALLBACK, tail.LOCAL, tail.NESTED, tail.EXTERNAL_ORIGIN,
            tail.BUILTIN, tail.ATTR, tail.PATH_CALL, tail.UNCLASSIFIED,
        }
