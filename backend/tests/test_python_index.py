import hashlib
import time

import pytest

from patchwork.errors import PatchworkError
from patchwork.ingestion.discovery import SourceFile
from patchwork.intelligence.models import ParsedFile
from patchwork.intelligence.python import parse_python


def parse(source: str, path: str = "pkg/example.py", limit: int = 100) -> ParsedFile:
    raw = source.encode()
    return parse_python(
        SourceFile(path, hashlib.sha256(raw).hexdigest(), len(raw), "utf-8", source),
        deadline=time.monotonic() + 5,
        max_symbols=limit,
    )


def test_nested_definitions_async_and_locations() -> None:
    source = """class Outer:
    @staticmethod
    async def method(value: int) -> int:
        def inner():
            return value
        class Local:
            def nested(self):
                pass
        return inner()

def outer():
    class Inside:
        pass
"""
    result = parse(source)
    assert [(s.qualified_name, s.kind, s.parent) for s in result.symbols] == [
        ("pkg/example.py", "module", None),
        ("Outer", "class", None),
        ("Outer.method", "method", "Outer"),
        ("Outer.method.inner", "function", "Outer.method"),
        ("Outer.method.Local", "class", "Outer.method"),
        ("Outer.method.Local.nested", "method", "Outer.method.Local"),
        ("outer", "function", None),
        ("outer.Inside", "class", "outer"),
    ]
    method = result.symbols[2]
    assert method.is_async
    assert (method.start_line, method.end_line) == (3, 9)
    assert method.decorators == ("@staticmethod",)
    assert method.signature == "async def method(value: int) -> int:"
    assert source.encode()[method.start_byte : method.end_byte].decode().endswith("return inner()")
    assert not result.has_errors
    assert result == parse(source)


def test_imports_preserve_relative_names_and_scope() -> None:
    result = parse("""import os, package.child as alias
from ..package import (name as renamed, other)
from . import sibling
from external import *
from __future__ import annotations
def run():
    import conditional
""")
    assert [
        (i.module_name, i.imported_name, i.alias, i.relative_level, i.scope) for i in result.imports
    ] == [
        ("os", None, None, 0, None),
        ("package.child", None, "alias", 0, None),
        ("package", "name", "renamed", 2, None),
        ("package", "other", None, 2, None),
        ("", "sibling", None, 1, None),
        ("external", "*", None, 0, None),
        ("__future__", "annotations", None, 0, None),
        ("conditional", None, None, 0, "run"),
    ]
    assert result.imports[2].start_line == 2
    assert result.imports[2].statement.startswith("from ..package")


def test_unicode_and_crlf_source_locations() -> None:
    source = '# 你好\r\nasync def café():\r\n    return "é"\r\n'
    result = parse(source, "包/模块.py")
    symbol = result.symbols[1]
    assert symbol.name == "café"
    assert symbol.is_async
    assert (symbol.start_line, symbol.end_line) == (2, 3)
    assert (
        source.encode()[symbol.start_byte : symbol.end_byte].decode().startswith("async def café")
    )


def test_malformed_source_keeps_recoverable_symbols() -> None:
    result = parse("def valid():\n    pass\n\ndef broken(:\n    pass\n")
    assert result.has_errors
    assert any(symbol.name == "valid" for symbol in result.symbols)
    assert result.symbols[0].has_errors


def test_empty_module_and_missing_symbols() -> None:
    result = parse("")
    assert len(result.symbols) == 1
    assert result.symbols[0].kind == "module"
    assert (result.symbols[0].start_line, result.symbols[0].end_line) == (1, 1)
    assert result.imports == ()


def test_symbol_count_limit() -> None:
    with pytest.raises(PatchworkError) as failure:
        parse("def one(): pass\ndef two(): pass\n", limit=2)
    assert failure.value.code == "index_too_large"


def test_expired_parser_deadline() -> None:
    with pytest.raises(PatchworkError) as failure:
        parse_python(SourceFile("a.py", "hash", 0, "utf-8", ""), deadline=0, max_symbols=10)
    assert failure.value.code == "ingestion_timeout"
