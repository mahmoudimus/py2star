"""
Scope declarations Starlark does not have: ``nonlocal`` and ``global``.
"""
import typing

import libcst as cst
import libcst.matchers as m
from libcst import codemod
from libcst.metadata import ExpressionContext, ExpressionContextProvider

from py2star.asteez.remove_exceptions import _AssignedNames


def _direct_statements(fn: cst.FunctionDef, kind) -> typing.List[cst.CSTNode]:
    """Statements of type ``kind`` in fn, excluding nested functions/classes."""
    found = []

    class _Finder(cst.CSTVisitor):
        def on_visit(self, node: cst.CSTNode) -> bool:
            if isinstance(node, kind):
                found.append(node)
            return not isinstance(node, (cst.FunctionDef, cst.ClassDef))

    for stmt in fn.body.body:
        stmt.visit(_Finder())
    return found


def _param_names(fn: cst.FunctionDef) -> typing.Set[str]:
    p = fn.params
    params = [*p.posonly_params, *p.params, *p.kwonly_params]
    for star in (p.star_arg, p.star_kwarg):
        if isinstance(star, cst.Param):
            params.append(star)
    return {param.name.value for param in params}


def _local_names(fn: cst.FunctionDef) -> typing.Set[str]:
    collector = _AssignedNames()
    for stmt in fn.body.body:
        stmt.visit(collector)
    return set(collector.names) | _param_names(fn)


def _with_prologue(
    fn: cst.FunctionDef, prologue: typing.List[cst.BaseStatement]
) -> cst.FunctionDef:
    body = list(fn.body.body)
    at = (
        1
        if body
        and m.matches(body[0], m.SimpleStatementLine([m.Expr(m.SimpleString())]))
        else 0
    )
    return fn.with_changes(
        body=fn.body.with_changes(body=body[:at] + prologue + body[at:])
    )


class BoxNonlocals(codemod.ContextAwareTransformer):
    """
    Starlark closures can read, but not rebind, variables of the enclosing
    function. A variable that an inner function declares ``nonlocal`` is kept
    in a one-element list instead, which the inner function can mutate:

        def counter():
            count = 0
            def inc():
                nonlocal count
                count += 1
            inc()
            return count

    becomes:

        def counter():
            count = [None]
            count[0] = 0
            def inc():
                count[0] += 1
            inc()
            return count[0]
    """

    METADATA_DEPENDENCIES = (ExpressionContextProvider,)

    def visit_Module(self, node: cst.Module) -> bool:
        # function -> names it owns that inner functions declare nonlocal
        self.owned: typing.Dict[cst.FunctionDef, typing.Set[str]] = {}
        self.nonlocals: typing.Dict[cst.FunctionDef, typing.Set[str]] = {}
        stack: typing.List[cst.FunctionDef] = []
        transformer = self

        class _Owners(cst.CSTVisitor):
            def visit_FunctionDef(self, fn: cst.FunctionDef) -> None:
                names = {
                    item.name.value
                    for stmt in _direct_statements(fn, cst.Nonlocal)
                    for item in stmt.names
                }
                transformer.nonlocals[fn] = names
                for name in names:
                    for outer in reversed(stack):
                        if name not in transformer.nonlocals[outer]:
                            transformer.owned.setdefault(outer, set()).add(name)
                            break
                stack.append(fn)

            def leave_FunctionDef(self, fn: cst.FunctionDef) -> None:
                stack.pop()

        node.visit(_Owners())
        self.active: typing.List[typing.Set[str]] = []
        # names that define rather than reference (params, def/class names)
        self.definitions: typing.Set[cst.Name] = set()
        return bool(self.owned)

    def visit_Param(self, node: cst.Param) -> None:
        self.definitions.add(node.name)

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self.definitions.add(node.name)

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self.definitions.add(node.name)
        parent = self.active[-1] if self.active else set()
        declared = self.nonlocals.get(node, set())
        shadowed = _local_names(node) - declared
        self.active.append((parent - shadowed) | self.owned.get(node, set()))

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        self.active.pop()
        owned = self.owned.get(original_node)
        if not owned:
            return updated_node
        params = _param_names(original_node)
        return _with_prologue(
            updated_node,
            [
                cst.parse_statement(
                    f"{n} = [{n}]" if n in params else f"{n} = [None]"
                )
                for n in sorted(owned)
            ],
        )

    def visit_Nonlocal(self, node: cst.Nonlocal) -> bool:
        return False

    def leave_Nonlocal(self, original_node, updated_node):
        return cst.RemoveFromParent()

    def leave_Name(
        self, original_node: cst.Name, updated_node: cst.Name
    ) -> cst.BaseExpression:
        if (
            not self.active
            or updated_node.value not in self.active[-1]
            or original_node in self.definitions
        ):
            return updated_node
        ctx = self.get_metadata(ExpressionContextProvider, original_node, None)
        if ctx not in (ExpressionContext.LOAD, ExpressionContext.STORE):
            return updated_node
        return cst.Subscript(
            value=updated_node,
            slice=[cst.SubscriptElement(cst.Index(cst.Integer("0")))],
        )


class FlagGlobals(codemod.ContextAwareTransformer):
    """
    Module globals are frozen once a Starlark module has loaded, so a
    function cannot rebind or mutate them. ``global x`` is removed and
    flagged for a manual port.
    """

    def leave_SimpleStatementLine(
        self,
        original_node: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> cst.SimpleStatementLine:
        globals_ = [s for s in updated_node.body if isinstance(s, cst.Global)]
        if not globals_:
            return updated_node
        names = ", ".join(i.name.value for g in globals_ for i in g.names)
        body = [s for s in updated_node.body if not isinstance(s, cst.Global)]
        return updated_node.with_changes(
            body=body or [cst.Pass()],
            leading_lines=[
                *updated_node.leading_lines,
                cst.EmptyLine(
                    comment=cst.Comment(
                        f"# PY2LARKY: `global {names}` is not supported; "
                        "module globals are frozen after load"
                    )
                ),
            ],
        )
