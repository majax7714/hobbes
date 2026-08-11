"""Module docstring capture and normalization (hobbes.extract.docstrings)."""

from __future__ import annotations

from hobbes.extract.docstrings import module_docstring, summary
from hobbes.extract.pysource import parse_source


def parsed(source: str):
    return parse_source(source.encode())


class TestCapture:
    def test_the_literal_is_captured_verbatim(self):
        # pysource extracts; normalizing is the other module's job.
        assert parsed('"""Hello."""\n').docstring == '"""Hello."""'

    def test_a_module_without_one_captures_none(self):
        assert parsed("import os\n").docstring is None

    def test_a_leading_expression_that_is_not_a_string_is_not_a_docstring(self):
        assert parsed("print('hi')\n").docstring is None

    def test_an_empty_module_has_none(self):
        assert parsed("").docstring is None


class TestNormalize:
    def test_triple_quotes_are_stripped(self):
        assert module_docstring(parsed('"""Hello."""\n')) == "Hello."

    def test_single_quotes_are_stripped(self):
        assert module_docstring(parsed("'One line.'\n")) == "One line."

    def test_a_prefixed_literal_is_handled(self):
        assert module_docstring(parsed('r"""Raw."""\n')) == "Raw."

    def test_none_survives(self):
        assert module_docstring(parsed("import os\n")) is None
        assert summary(parsed("import os\n")) is None


class TestSummary:
    def test_the_first_paragraph_becomes_one_line(self):
        source = '"""First line\nstill first.\n\nSecond paragraph."""\n'
        assert summary(parsed(source)) == "First line still first."

    def test_a_one_paragraph_docstring_is_returned_whole(self):
        assert summary(parsed('"""Just this."""\n')) == "Just this."

    def test_a_whitespace_only_docstring_is_none(self):
        assert summary(parsed('"""   """\n')) is None
