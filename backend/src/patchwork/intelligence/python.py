"""Python syntax only: lexical scopes are not inferred call/import relationships."""

import time
from pathlib import PurePosixPath

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from patchwork.errors import PatchworkError
from patchwork.ingestion.discovery import SourceFile
from patchwork.intelligence.models import Import, ParsedFile, Symbol

LANGUAGE = Language(tree_sitter_python.language())


def text(node: Node | None) -> str:
    return node.text.decode("utf-8") if node is not None and node.text is not None else ""


def end_line(node: Node) -> int:
    return max(node.start_point.row + 1, node.end_point.row + (node.end_point.column != 0))


def extract_imports(
    node: Node, path: str, scope: str | None, deadline: float, max_items: int
) -> list[Import]:
    if node.has_error:
        return []
    module = text(node.child_by_field_name("module_name"))
    if node.type == "future_import_statement":
        module = "__future__"
    level = len(module) - len(module.lstrip("."))
    result = []
    statement = text(node)[:2000]
    names = list(node.children_by_field_name("name"))
    names.extend(child for child in node.named_children if child.type == "wildcard_import")
    for target in names:
        if time.monotonic() >= deadline:
            raise PatchworkError("ingestion_timeout", "Python indexing timed out.", 504)
        if len(result) >= max_items:
            raise PatchworkError("index_too_large", "Import count exceeds the limit.", 413)
        name = (
            text(target.child_by_field_name("name"))
            if target.type == "aliased_import"
            else text(target)
        )
        alias = text(target.child_by_field_name("alias")) or None
        if max(len(module), len(name), len(alias or "")) > 4096:
            raise PatchworkError(
                "index_too_large", "Import identifiers exceed the indexing limit.", 413
            )
        result.append(
            Import(
                path=path,
                module_name=name if node.type == "import_statement" else module.lstrip("."),
                imported_name=None if node.type == "import_statement" else name,
                alias=alias,
                relative_level=level,
                scope=scope,
                start_line=node.start_point.row + 1,
                end_line=end_line(node),
                start_byte=target.start_byte,
                statement=statement,
            )
        )
    return result


def parse_python(file: SourceFile, *, deadline: float, max_symbols: int) -> ParsedFile:
    def check_budget() -> None:
        if time.monotonic() >= deadline:
            raise PatchworkError("ingestion_timeout", "Python indexing timed out.", 504)
        if len(symbols) + len(imports) > max_symbols:
            raise PatchworkError(
                "index_too_large", "Symbol and import count exceeds the limit.", 413
            )

    symbols: list[Symbol] = []
    imports: list[Import] = []
    check_budget()
    raw = file.source.encode("utf-8")
    parser = Parser(LANGUAGE)
    tree = parser.parse(
        lambda offset, _point: raw[offset : offset + 8192],
        progress_callback=lambda _offset, _has_error: time.monotonic() >= deadline,
    )
    if tree is None:
        raise PatchworkError("ingestion_timeout", "Python indexing timed out.", 504)
    root = tree.root_node
    symbols.append(
        Symbol(
            path=file.path,
            name=PurePosixPath(file.path).stem,
            qualified_name=file.path,
            kind="module",
            start_line=1,
            end_line=max(1, len(file.source.splitlines())),
            start_byte=0,
            end_byte=len(raw),
            has_errors=root.has_error,
        )
    )
    # Explicit stack avoids Python recursion limits on hostile or deeply nested input.
    stack: list[tuple[Node, tuple[tuple[str, str], ...], tuple[str, ...]]] = [(root, (), ())]
    while stack:
        check_budget()
        node, scope, decorators = stack.pop()
        parent = ".".join(name for name, _kind in scope) or None
        if node.type == "decorated_definition":
            definition = node.child_by_field_name("definition")
            if definition is not None:
                decorators = tuple(
                    text(child)[:512] for child in node.named_children if child.type == "decorator"
                )
                stack.append((definition, scope, decorators))
            continue
        if node.type in {"function_definition", "class_definition"}:
            identifier = node.child_by_field_name("name")
            if identifier is None or identifier.is_missing:
                continue
            name = text(identifier)
            qualified = f"{parent}.{name}" if parent else name
            if len(qualified) > 4096 or len(name) > 512:
                raise PatchworkError(
                    "index_too_large", "Symbol identifiers exceed the indexing limit.", 413
                )
            kind = (
                "class"
                if node.type == "class_definition"
                else "method"
                if scope and scope[-1][1] == "class"
                else "function"
            )
            body = node.child_by_field_name("body")
            signature_end = body.start_byte if body else node.end_byte
            symbols.append(
                Symbol(
                    path=file.path,
                    name=name,
                    qualified_name=qualified,
                    kind=kind,
                    parent=parent,
                    is_async=any(child.type == "async" for child in node.children),
                    start_line=node.start_point.row + 1,
                    end_line=end_line(node),
                    start_byte=node.start_byte,
                    end_byte=node.end_byte,
                    signature=raw[node.start_byte : signature_end].decode("utf-8").strip()[:512],
                    decorators=decorators,
                    has_errors=node.has_error,
                )
            )
            if body:
                stack.append((body, (*scope, (name, kind)), ()))
            continue
        if node.type in {"import_statement", "import_from_statement", "future_import_statement"}:
            imports.extend(
                extract_imports(
                    node, file.path, parent, deadline, max_symbols - len(symbols) - len(imports)
                )
            )
            continue
        stack.extend((child, scope, ()) for child in reversed(node.named_children))
    check_budget()
    return ParsedFile(
        file=file, has_errors=root.has_error, symbols=tuple(symbols), imports=tuple(imports)
    )
