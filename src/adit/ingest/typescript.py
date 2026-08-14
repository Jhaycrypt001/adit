"""Pass 1: parse one TypeScript/JavaScript file into declarations and bindings.

This pass is deliberately *local*. It records what a file declares, what it
imports, and what it exports, without trying to resolve any of it -- resolution
needs the whole project and happens in pass 2 (`project.py`).

Keeping the passes apart is what makes cross-file binding tractable. A call to
`merge()` cannot be bound until we know which module `merge` was imported from,
which module that specifier resolves to, and what that module actually exports
(possibly re-exported from somewhere else again).

Scope handling: every call site is attributed to the function that lexically
contains it. Calls at module top level are attributed to a synthetic `<module>`
symbol, because top-level code really does execute on import and is a genuine
entrypoint -- dropping it would silently lose reachability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

#: Synthetic symbol owning module-level statements.
MODULE_SCOPE = "<module>"

_TS = Language(tree_sitter_typescript.language_typescript())
_TSX = Language(tree_sitter_typescript.language_tsx())
_JS = Language(tree_sitter_javascript.language())

_BY_SUFFIX = {
    ".ts": _TS, ".mts": _TS, ".cts": _TS,
    ".tsx": _TSX,
    ".js": _JS, ".mjs": _JS, ".cjs": _JS, ".jsx": _JS,
}

#: Nodes that introduce a new callable scope.
_FUNCTIONISH = {
    "function_declaration",
    "generator_function_declaration",
    "function_expression",
    "generator_function",
    "arrow_function",
    "method_definition",
}


@dataclass(slots=True)
class CallSite:
    """An unresolved call, as written."""

    name: str            # "merge" or "lodash.merge"
    base: str | None     # "lodash" for member calls, else None
    member: str | None   # "merge" for member calls, else None
    line: int


@dataclass(slots=True)
class SymbolInfo:
    """A callable declared in this file."""

    name: str            # "handleOrder" or "OrderService.handle" or "<module>"
    kind: str            # function | method | arrow | class | module
    line: int
    exported: bool = False
    calls: list[CallSite] = field(default_factory=list)


@dataclass(slots=True)
class ImportBinding:
    """A name this module pulled in from elsewhere."""

    local: str           # the name as used here
    source: str          # specifier exactly as written
    imported: str        # name in the source module; "*" namespace, "default" default


@dataclass(slots=True)
class ExportBinding:
    """A name this module makes visible to importers."""

    exported: str
    local: str | None = None       # defined here under this local name
    source: str | None = None      # or re-exported from this specifier
    imported: str | None = None    # ...under this name there ("*" for star)


@dataclass(slots=True)
class ModuleInfo:
    """Everything pass 1 learned about one file."""

    path: str
    symbols: dict[str, SymbolInfo] = field(default_factory=dict)
    imports: dict[str, ImportBinding] = field(default_factory=dict)
    exports: dict[str, ExportBinding] = field(default_factory=dict)
    star_reexports: list[str] = field(default_factory=list)
    #: (enclosing scope, variable name) -> class name, from `const x = new Foo()`.
    #:
    #: Not type inference -- just the one narrow case that dominates real
    #: TypeScript: a local bound directly to a constructor call. It lets
    #: `svc.handle()` bind to `OrderService.handle`, which otherwise needs a
    #: type checker. Only the FIRST binding in a scope is kept, so a later
    #: reassignment degrades to unresolved rather than to a wrong answer.
    local_types: dict[tuple[str, str], str] = field(default_factory=dict)
    parse_errors: int = 0

    def specifiers(self) -> set[str]:
        """Every module specifier this file references."""
        out = {b.source for b in self.imports.values()}
        out |= {e.source for e in self.exports.values() if e.source}
        out |= set(self.star_reexports)
        return out


def _text(node: Node) -> str:
    return node.text.decode("utf-8", "replace") if node.text else ""


def _require_source(node: Node) -> str | None:
    """If `node` is `require('x')`, return `x`; otherwise None.

    Only literal specifiers are accepted. `require(someVariable)` is genuinely
    unresolvable without evaluating the program, and is declared out of scope in
    the README rather than guessed at.
    """
    if node.type != "call_expression":
        return None
    fn = node.child_by_field_name("function")
    if fn is None or fn.type != "identifier" or _text(fn) != "require":
        return None
    args = node.child_by_field_name("arguments")
    if args is None:
        return None
    for child in args.children:
        if child.type == "string":
            return _text(child).strip("'\"`")
    return None


def _line(node: Node) -> int:
    return node.start_point[0] + 1


class _Walker:
    """Recursive descent that tracks the enclosing callable."""

    def __init__(self, path: str) -> None:
        self.mod = ModuleInfo(path=path)
        self.mod.symbols[MODULE_SCOPE] = SymbolInfo(
            name=MODULE_SCOPE, kind="module", line=1, exported=False
        )

    # -- symbol naming -----------------------------------------------------
    def _declare(self, name: str, kind: str, node: Node, *, exported: bool) -> str:
        """Register a symbol, keeping the first declaration of a duplicate name.

        Duplicates happen legitimately (overloads, conditional declarations).
        Taking the first keeps binding deterministic across runs, which matters
        because node ids are hashes of these names.
        """
        if name not in self.mod.symbols:
            self.mod.symbols[name] = SymbolInfo(
                name=name, kind=kind, line=_line(node), exported=exported
            )
        elif exported:
            self.mod.symbols[name].exported = True
        return name

    # -- traversal ---------------------------------------------------------
    def walk(self, node: Node, scope: str, *, exported: bool = False) -> None:
        kind = node.type

        if kind == "import_statement":
            self._import(node)
            return
        if kind == "export_statement":
            self._export(node, scope)
            return
        if kind in ("function_declaration", "generator_function_declaration"):
            self._function(node, scope, exported=exported)
            return
        if kind == "class_declaration":
            self._class(node, scope, exported=exported)
            return
        if kind == "lexical_declaration" or kind == "variable_declaration":
            self._variables(node, scope, exported=exported)
            return
        if kind == "assignment_expression":
            self._assignment(node, scope)
            # fall through: the right-hand side may contain calls
        if kind == "call_expression":
            self._call(node, scope)
            # fall through: arguments may contain further calls

        for child in node.children:
            self.walk(child, scope)

    # -- declarations ------------------------------------------------------
    def _function(self, node: Node, scope: str, *, exported: bool) -> None:
        name_node = node.child_by_field_name("name")
        name = _text(name_node) if name_node else f"<anon@{_line(node)}>"
        qualified = self._declare(name, "function", node, exported=exported)
        body = node.child_by_field_name("body")
        if body:
            self.walk(body, qualified)

    def _class(self, node: Node, scope: str, *, exported: bool) -> None:
        name_node = node.child_by_field_name("name")
        cls = _text(name_node) if name_node else f"<anonclass@{_line(node)}>"
        self._declare(cls, "class", node, exported=exported)

        body = node.child_by_field_name("body")
        if not body:
            return
        for member in body.children:
            if member.type != "method_definition":
                self.walk(member, scope)
                continue
            m_name = member.child_by_field_name("name")
            # `Class.method` keeps methods distinguishable across classes while
            # staying a plain string, which is all the key format allows.
            qualified = self._declare(
                f"{cls}.{_text(m_name) if m_name else 'anonymous'}",
                "method",
                member,
                exported=exported,
            )
            m_body = member.child_by_field_name("body")
            if m_body:
                self.walk(m_body, qualified)

    def _variables(self, node: Node, scope: str, *, exported: bool) -> None:
        """`const handle = () => {...}` declares a callable; other consts do not."""
        for declarator in node.children:
            if declarator.type != "variable_declarator":
                continue
            name_node = declarator.child_by_field_name("name")
            value = declarator.child_by_field_name("value")
            if not name_node:
                continue

            # CommonJS import. Most of npm -- lodash included -- is CJS, and
            # stage D has to parse dependency source, so this is not optional.
            source = _require_source(value) if value is not None else None
            if source is not None:
                self._require(name_node, source)
                continue

            name = _text(name_node)

            if value is not None and value.type in ("arrow_function", "function_expression"):
                qualified = self._declare(name, "arrow", declarator, exported=exported)
                body = value.child_by_field_name("body")
                if body:
                    self.walk(body, qualified)
            elif value is not None and value.type == "new_expression":
                # `const svc = new OrderService()` -- remember the type so a
                # later `svc.handle()` can bind. First binding wins.
                ctor = value.child_by_field_name("constructor")
                if ctor is not None and ctor.type == "identifier":
                    self.mod.local_types.setdefault((scope, name), _text(ctor))
                self.walk(value, scope)
            elif (
                value is not None
                and value.type == "call_expression"
                and scope == MODULE_SCOPE
            ):
                # `var merge = createAssigner(function (a, b) { baseMerge(...) })`
                #
                # A callable produced by a factory or higher-order function is
                # still a callable, and in real JavaScript this is how much of a
                # package's public surface is defined -- lodash's `merge` among
                # them. Declaring it makes the symbol findable, and walking the
                # value under that scope attributes the inner calls to it, which
                # is what yields `merge -> baseMerge`.
                #
                # Restricted to module scope on purpose. Inside a function body,
                # `const clean = normalize(payload)` is an ordinary local result
                # and the call belongs to the *enclosing* function -- attributing
                # it to `clean` would silently break every call chain that passes
                # through a local variable.
                qualified = self._declare(name, "binding", declarator, exported=exported)
                self.walk(value, qualified)
            elif value is not None:
                # A non-callable initialiser can still contain calls, and those
                # execute at module load.
                self.walk(value, scope)

    # -- CommonJS ----------------------------------------------------------
    def _require(self, name_node: Node, source: str) -> None:
        """`const merge = require('lodash')` / `const {merge} = require('lodash')`."""
        if name_node.type == "identifier":
            local = _text(name_node)
            # A whole-module binding behaves like a namespace import: later
            # `merge.foo()` resolves against the target's exports.
            self.mod.imports[local] = ImportBinding(local, source, "*")
            return

        if name_node.type == "object_pattern":
            for child in name_node.children:
                if child.type == "shorthand_property_identifier_pattern":
                    local = _text(child)
                    self.mod.imports[local] = ImportBinding(local, source, local)
                elif child.type == "pair_pattern":
                    key = child.child_by_field_name("key")
                    val = child.child_by_field_name("value")
                    if key is not None and val is not None:
                        self.mod.imports[_text(val)] = ImportBinding(
                            _text(val), source, _text(key)
                        )

    def _assignment(self, node: Node, scope: str) -> None:
        """Detect CommonJS exports: `module.exports.x =`, `exports.x =`, `module.exports =`."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None:
            return

        # `exports = module.exports = createApplication` -- express and much of
        # older npm write this. Unwrap to the innermost value, and treat the
        # whole chain as a default-export assignment.
        while right is not None and right.type == "assignment_expression":
            right = right.child_by_field_name("right")

        target: str | None
        if left.type == "identifier" and _text(left) == "exports":
            target = None                            # exports = ...
        elif left.type == "member_expression":
            obj = left.child_by_field_name("object")
            prop = left.child_by_field_name("property")
            if obj is None or prop is None:
                return
            obj_text, prop_text = _text(obj), _text(prop)
            if obj_text == "exports":
                target = prop_text                   # exports.foo = ...
            elif obj_text == "module" and prop_text == "exports":
                target = None                        # module.exports = ...
            elif obj_text == "module.exports":
                target = prop_text                   # module.exports.foo = ...
            else:
                return
        else:
            return

        if target is None:
            # `module.exports = { a, b }` -- each shorthand key is an export.
            if right is not None and right.type == "object":
                for pair in right.children:
                    if pair.type == "shorthand_property_identifier":
                        name = _text(pair)
                        self.mod.exports[name] = ExportBinding(exported=name, local=name)
                        if name in self.mod.symbols:
                            self.mod.symbols[name].exported = True
                    elif pair.type == "pair":
                        key = pair.child_by_field_name("key")
                        val = pair.child_by_field_name("value")
                        if key is not None and val is not None and val.type == "identifier":
                            self.mod.exports[_text(key)] = ExportBinding(
                                exported=_text(key), local=_text(val)
                            )
                            if _text(val) in self.mod.symbols:
                                self.mod.symbols[_text(val)].exported = True
            elif right is not None and right.type == "identifier":
                # `module.exports = foo` -- foo is the default export. Many
                # single-purpose npm modules (lodash/merge.js among them) look
                # exactly like this, so the package's whole public surface
                # depends on catching it.
                name = _text(right)
                self.mod.exports["default"] = ExportBinding(exported="default", local=name)
                self.mod.exports.setdefault(name, ExportBinding(exported=name, local=name))
                if name in self.mod.symbols:
                    self.mod.symbols[name].exported = True
            elif right is not None and right.type in (
                "function_expression", "arrow_function", "generator_function"
            ):
                # `module.exports = function name() {}` -- may be anonymous, in
                # which case the module itself is the callable.
                name_node = right.child_by_field_name("name")
                name = _text(name_node) if name_node else "default"
                self._declare(name, "function", right, exported=True)
                self.mod.exports["default"] = ExportBinding(exported="default", local=name)
                body = right.child_by_field_name("body")
                if body:
                    self.walk(body, name)
            return

        # `exports.foo = bar` / `module.exports.foo = bar`
        local = _text(right) if right is not None and right.type == "identifier" else target
        self.mod.exports[target] = ExportBinding(exported=target, local=local)
        if local in self.mod.symbols:
            self.mod.symbols[local].exported = True

    # -- imports / exports -------------------------------------------------
    def _import(self, node: Node) -> None:
        source_node = node.child_by_field_name("source")
        if not source_node:
            return
        source = _text(source_node).strip("'\"`")

        clause = next((c for c in node.children if c.type == "import_clause"), None)
        if clause is None:
            # `import './side-effect'` -- no bindings, but the edge is real.
            self.mod.star_reexports.append(source) if False else None
            self.mod.imports.setdefault(
                f"<side-effect:{source}>",
                ImportBinding(local=f"<side-effect:{source}>", source=source, imported="*"),
            )
            return

        for child in clause.children:
            if child.type == "identifier":  # default import
                local = _text(child)
                self.mod.imports[local] = ImportBinding(local, source, "default")
            elif child.type == "namespace_import":
                ident = next((c for c in child.children if c.type == "identifier"), None)
                if ident:
                    local = _text(ident)
                    self.mod.imports[local] = ImportBinding(local, source, "*")
            elif child.type == "named_imports":
                for spec in child.children:
                    if spec.type != "import_specifier":
                        continue
                    name_node = spec.child_by_field_name("name")
                    alias_node = spec.child_by_field_name("alias")
                    if not name_node:
                        continue
                    imported = _text(name_node)
                    local = _text(alias_node) if alias_node else imported
                    self.mod.imports[local] = ImportBinding(local, source, imported)

    def _export(self, node: Node, scope: str) -> None:
        source_node = node.child_by_field_name("source")
        source = _text(source_node).strip("'\"`") if source_node else None

        # `export * from './x'` -- the barrel-file case that defeats naive tools.
        if source and any(c.type == "*" for c in node.children):
            self.mod.star_reexports.append(source)
            return

        clause = next((c for c in node.children if c.type == "export_clause"), None)
        if clause is not None:
            for spec in clause.children:
                if spec.type != "export_specifier":
                    continue
                name_node = spec.child_by_field_name("name")
                alias_node = spec.child_by_field_name("alias")
                if not name_node:
                    continue
                local = _text(name_node)
                exported = _text(alias_node) if alias_node else local
                if source:
                    self.mod.exports[exported] = ExportBinding(
                        exported=exported, source=source, imported=local
                    )
                else:
                    self.mod.exports[exported] = ExportBinding(exported=exported, local=local)
                    if local in self.mod.symbols:
                        self.mod.symbols[local].exported = True
            return

        # `export function f() {}` / `export const g = () => {}` / `export default ...`
        declaration = node.child_by_field_name("declaration")
        if declaration is not None:
            before = set(self.mod.symbols)
            self.walk(declaration, scope, exported=True)
            for name in set(self.mod.symbols) - before:
                self.mod.exports[name] = ExportBinding(exported=name, local=name)
            return

        for child in node.children:
            self.walk(child, scope)

    # -- calls -------------------------------------------------------------
    def _call(self, node: Node, scope: str) -> None:
        fn = node.child_by_field_name("function")
        if fn is None:
            return
        if fn.type == "identifier":
            name = _text(fn)
            self.mod.symbols[scope].calls.append(CallSite(name, None, None, _line(node)))
        elif fn.type == "member_expression":
            obj = fn.child_by_field_name("object")
            prop = fn.child_by_field_name("property")
            if obj is not None and prop is not None:
                base, member = _text(obj), _text(prop)
                self.mod.symbols[scope].calls.append(
                    CallSite(f"{base}.{member}", base, member, _line(node))
                )


def parse_file(path: Path, root: Path) -> ModuleInfo | None:
    """Parse one source file. Returns None for unsupported or unreadable files."""
    language = _BY_SUFFIX.get(path.suffix)
    if language is None:
        return None
    try:
        source = path.read_bytes()
    except OSError:
        return None

    parser = Parser(language)
    tree = parser.parse(source)

    rel = path.relative_to(root).as_posix()
    walker = _Walker(rel)
    walker.walk(tree.root_node, MODULE_SCOPE)

    # A file that fails to parse cleanly still yields partial results; record
    # the fact so ingest can report coverage honestly rather than silently
    # under-reporting the call graph.
    if tree.root_node.has_error:
        walker.mod.parse_errors = 1
    return walker.mod
