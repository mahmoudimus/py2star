import typing
from typing import Union

import libcst as cst
from libcst import (
    BaseSmallStatement,
    BaseStatement,
    FlattenSentinel,
    Raise,
    RemovalSentinel,
    SimpleStatementLine,
    Try,
    codemod,
    ensure_type,
)
import libcst.matchers as m
from libcst.codemod import CodemodContext
from libcst.codemod.visitors import AddImportsVisitor
from libcst.metadata import ParentNodeProvider


class AssertStatementRewriter(codemod.ContextAwareTransformer):
    """
    assert 1 == 1, "what?"
    |_ => if not (1 == 1):
    |_ =>     fail("what?")
    assert 1 != 2
    assert 1 == 2
    """

    def __init__(self, context, for_tests=False):
        super(AssertStatementRewriter, self).__init__(context)
        self.for_tests = for_tests

    @m.call_if_inside(
        m.SimpleStatementLine(
            body=[m.Assert(test=m.DoNotCare(), msg=m.DoNotCare())]
        )
    )
    def leave_SimpleStatementLine(
        self,
        original_node: "SimpleStatementLine",
        updated_node: "SimpleStatementLine",
    ) -> Union[
        "BaseStatement", FlattenSentinel["BaseStatement"], RemovalSentinel
    ]:
        assert_stmt = ensure_type(updated_node.body[0], cst.Assert)
        msg = assert_stmt.msg
        if not msg:
            msg = cst.SimpleString(
                f'"{self.module.code_for_node(assert_stmt)} failed!"'
            )
        if_stmt = cst.If(
            test=cst.UnaryOperation(
                operator=cst.Not(),
                expression=assert_stmt.test.with_changes(
                    lpar=[
                        cst.LeftParen(
                            whitespace_after=cst.SimpleWhitespace(
                                value="",
                            ),
                        ),
                    ],
                    rpar=[
                        cst.RightParen(
                            whitespace_before=cst.SimpleWhitespace(
                                value="",
                            ),
                        ),
                    ],
                ),
            ),
            body=cst.IndentedBlock(
                body=[
                    cst.SimpleStatementLine(
                        body=[
                            cst.Expr(
                                value=cst.Call(
                                    func=cst.Name(
                                        value="fail",
                                        lpar=[],
                                        rpar=[],
                                    ),
                                    args=[cst.Arg(value=msg)],
                                )
                            )
                        ],
                    ),
                ],
            ),
        )
        return updated_node.deep_replace(updated_node, if_stmt)


class RemoveExceptions(codemod.ContextAwareTransformer):
    def __init__(self, context=None):
        context = context if context else CodemodContext()
        super(RemoveExceptions, self).__init__(context)

    DESCRIPTION = "Removes exceptions."
    METADATA_DEPENDENCIES = (ParentNodeProvider,)

    def leave_Try(
        self, original_node: "Try", updated_node: "Try"
    ) -> Union[
        "BaseStatement", FlattenSentinel["BaseStatement"], RemovalSentinel
    ]:
        # TODO: check to see https://github.com/MaT1g3R/option/issues/7
        # need to come to an agreement on how this will work.
        return updated_node

    def visit_Module(self, node: cst.Module) -> bool:
        # raise statements whose message needs a manual look
        self._flagged = set()
        return True

    def leave_SimpleStatementLine(
        self,
        original_node: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> cst.SimpleStatementLine:
        if not any(stmt in self._flagged for stmt in original_node.body):
            return updated_node
        return updated_node.with_changes(
            leading_lines=[
                *updated_node.leading_lines,
                cst.EmptyLine(
                    comment=cst.Comment("# PY2LARKY: pay attention to this!")
                ),
            ]
        )

    def _config(self, key):
        _config = self.context.scratch.get("config") or {}
        return _config.get(key, False)

    def _enclosing(self, node: cst.CSTNode):
        """Yield (child, parent) pairs up to the enclosing function."""
        child, parent = node, self.get_metadata(ParentNodeProvider, node, None)
        while parent is not None and not isinstance(
            parent, (cst.FunctionDef, cst.Lambda, cst.ClassDef)
        ):
            yield child, parent
            child, parent = parent, self.get_metadata(
                ParentNodeProvider, parent, None
            )

    def _in_try_body(self, node: cst.CSTNode) -> bool:
        """True if node runs inside a ``try:`` body of the enclosing function,
        where a raise must actually raise so the try can catch it."""
        return any(
            isinstance(parent, cst.Try) and child is parent.body
            for child, parent in self._enclosing(node)
        )

    def _in_handler(self, node: cst.CSTNode) -> bool:
        return any(
            isinstance(parent, cst.ExceptHandler)
            for _, parent in self._enclosing(node)
        )

    @staticmethod
    def _exc_name(exc: cst.BaseExpression) -> str:
        if isinstance(exc, cst.Call):
            exc = exc.func
        if isinstance(exc, cst.Attribute):
            return exc.attr.value
        return ensure_type(exc, cst.Name).value

    @staticmethod
    def _is_str_expr(value: cst.BaseExpression) -> bool:
        if isinstance(
            value,
            (cst.SimpleString, cst.ConcatenatedString, cst.FormattedString),
        ):
            return True
        if isinstance(value, cst.BinaryOperation) and isinstance(
            value.operator, (cst.Add, cst.Modulo)
        ):
            return RemoveExceptions._is_str_expr(value.left)
        # "...".format(...), "".join(...), etc.
        return m.matches(
            value,
            m.Call(
                func=m.Attribute(
                    value=m.SimpleString()
                    | m.ConcatenatedString()
                    | m.FormattedString()
                )
            ),
        )

    def _message(self, exc: cst.BaseExpression) -> cst.BaseExpression:
        """Build the fail()/Error() message: "ExcName: <original message>"."""
        name = self._exc_name(exc)
        args = exc.args if isinstance(exc, cst.Call) else ()
        if not args:
            return cst.SimpleString(f'"{name}"')
        if len(args) > 1:
            msg = cst.Call(
                func=cst.Name("str"),
                args=[cst.Arg(cst.Tuple([cst.Element(a.value) for a in args]))],
            )
        else:
            msg = args[0].value
            if (
                isinstance(msg, cst.SimpleString)
                and "b" not in msg.prefix.lower()
            ):
                return msg.with_changes(
                    value=f"{msg.prefix}{msg.quote}{name}: "
                    f"{msg.raw_value}{msg.quote}"
                )
            if not self._is_str_expr(msg):
                msg = cst.Call(func=cst.Name("str"), args=[cst.Arg(msg)])
        return cst.BinaryOperation(
            left=cst.SimpleString(f'"{name}: "'),
            operator=cst.Add(),
            right=msg,
        )

    def leave_Raise(
        self, original_node: "Raise", updated_node: "Raise"
    ) -> Union[
        "BaseSmallStatement",
        FlattenSentinel["BaseSmallStatement"],
        RemovalSentinel,
    ]:
        exc = updated_node.exc
        if exc is None:
            if self._in_handler(original_node):
                # re-raise; rewritten by TryExceptToResult
                return updated_node
            # just naked raise, just replace w/ return
            return cst.Return(value=None)

        if m.matches(exc, m.Name() | m.Attribute()) and not self._exc_name(
            exc
        )[:1].isupper():
            # raise err -- an exception (message) held in a variable
            self._flagged.add(original_node)
            message = cst.Call(func=cst.Name("str"), args=[cst.Arg(exc)])
        else:
            message = self._message(exc)

        use_error = self._config("use_error_not_fail")
        unwrap = self._config("unwrap_errors") or (
            use_error and self._in_try_body(original_node)
        )
        if not (use_error or unwrap):
            return cst.Expr(
                value=cst.Call(func=cst.Name("fail"), args=[cst.Arg(message)])
            )

        AddImportsVisitor.add_needed_import(
            self.context, "option.result", "Error"
        )
        rval = cst.Call(func=cst.Name("Error"), args=[cst.Arg(message)])
        if unwrap:
            rval = cst.Call(
                func=cst.Attribute(value=rval, attr=cst.Name("unwrap"))
            )
        return cst.Return(value=rval)

class CommentTopLevelTryBlocks(codemod.ContextAwareTransformer):
    """
    remove top level import exceptions

    so imagine a module like this:

      .. python::

        try
            from _cexcept import *
        except ImportError:
            pass

        def foo():
            return "foo"

    this gets re-written to:

      .. python::

        # try
        #     from _cexcept import *
        # except ImportError:
        #     pass

        def foo():
            return "foo"

    Because Starlark does not have exceptions
    """

    METADATA_DEPENDENCIES = (
        cst.metadata.ScopeProvider,
        cst.metadata.PositionProvider,
    )

    def __init__(self, context=None):
        context = context if context else CodemodContext()
        super(CommentTopLevelTryBlocks, self).__init__(context)
        self._herp = []
        self._node = None

    def visit_Module(self, node: "Module") -> typing.Optional[bool]:
        return None

    def leave_Module(
        self, original_node: "Module", updated_node: "Module"
    ) -> "Module":
        if not self._herp:
            return updated_node
        body_ = []
        for b in updated_node.body:
            # identity `is` check here to find the *node* we marked!
            if b is self._node:
                # replace the node with the commented body
                body_.extend(self._herp)
                continue
            body_.append(b)
        return updated_node.with_changes(body=body_)
        # cst.parse_statement(f"", config=updated_node.config_for_parsing)
        # return updated_node

    def visit_Try(self, node: "Try") -> typing.Optional[bool]:
        pos = self.get_metadata(cst.metadata.PositionProvider, node)
        self._startpos = pos.start

    def leave_Try(
        self, original_node: "Try", updated_node: "Try"
    ) -> Union[
        "BaseStatement", FlattenSentinel["BaseStatement"], RemovalSentinel
    ]:
        pos = self.get_metadata(cst.metadata.PositionProvider, original_node)
        self._endpos = pos.end
        scope = self.get_metadata(cst.metadata.ScopeProvider, original_node)

        # # The below does not work for some reason
        # # TODO: figure it out
        # if m.matches(
        #     updated_node,
        #     m.Try(
        #         body=m.DoNotCare(),
        #         metadata=m.MatchMetadata(
        #             cst.metadata.ScopeProvider, {cst.metadata.GlobalScope()}
        #         ),
        #     ),
        # ):
        #     pass
        # Using isinstance as a back up for now.
        if not isinstance(scope, cst.metadata.GlobalScope):
            return updated_node
        codegen = cst.parse_module(
            "", config=self.context.module.config_for_parsing
        )
        self._herp = [
            self._comment_line(line)
            # we do -1 here to remove the trailing whitespace
            for line in codegen.code_for_node(updated_node).split("\n")[:-1]
        ]
        self._node = updated_node
        # we won't remove this from the parent b/c we plan on replacing the
        # exact position in the updated module:
        # return cst.RemoveFromParent()
        return updated_node

    def _comment_line(self, line):
        # TODO: the space between # and {line} should be determined by the node
        return cst.EmptyLine(comment=cst.Comment(value=f"# {line}"))


# Larky raises its own (unprefixed) messages for runtime errors; match them
# alongside "ExcName: ..." messages produced by RemoveExceptions.
_NATIVE_ERROR_PATTERNS = {
    "KeyError": ["not found in dictionary"],
    "IndexError": ["index out of range"],
    "ZeroDivisionError": ["division by zero", "modulo by zero"],
    "ValueError": ["invalid base-\\d+ literal", "not found in list"],
    "AttributeError": ["has no field or method"],
    "TypeError": ["unsupported (binary|unary) operation"],
}
_EXCEPTION_ALIASES = {
    "LookupError": ["LookupError", "KeyError", "IndexError"],
    "ArithmeticError": ["ArithmeticError", "ZeroDivisionError"],
}
_CATCH_ALL = {"Exception", "BaseException"}

_SCOPES = (cst.FunctionDef, cst.ClassDef, cst.Lambda)
_COMPREHENSIONS = (cst.ListComp, cst.SetComp, cst.DictComp, cst.GeneratorExp)


def _target_names(target: cst.BaseExpression) -> typing.List[str]:
    if isinstance(target, cst.Name):
        return [target.value]
    if isinstance(target, (cst.Tuple, cst.List)):
        return [n for e in target.elements for n in _target_names(e.value)]
    if isinstance(target, cst.StarredElement):
        return _target_names(target.value)
    return []


class _AssignedNames(cst.CSTVisitor):
    """Names bound directly in a block (not in nested scopes)."""

    def __init__(self) -> None:
        self.names: typing.List[str] = []

    def _add(self, names) -> None:
        self.names.extend(n for n in names if n not in self.names)

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        self._add([node.name.value])
        return False

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        self._add([node.name.value])
        return False

    def visit_Lambda(self, node: cst.Lambda) -> bool:
        return False

    def on_visit(self, node: cst.CSTNode) -> bool:
        if isinstance(node, _COMPREHENSIONS):
            return False
        return super().on_visit(node)

    def visit_Assign(self, node: cst.Assign) -> None:
        for t in node.targets:
            self._add(_target_names(t.target))

    def visit_AugAssign(self, node: cst.AugAssign) -> None:
        self._add(_target_names(node.target))

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        self._add(_target_names(node.target))

    def visit_For(self, node: cst.For) -> None:
        self._add(_target_names(node.target))

    def visit_WithItem(self, node: cst.WithItem) -> None:
        if node.asname:
            self._add(_target_names(node.asname.name))

    def visit_NamedExpr(self, node: cst.NamedExpr) -> None:
        self._add(_target_names(node.target))

    def visit_ImportAlias(self, node: cst.ImportAlias) -> None:
        if node.asname:
            self._add(_target_names(node.asname.name))
        else:
            name = node.name
            while isinstance(name, cst.Attribute):
                name = name.value
            self._add([name.value])


class _ControlFlow(cst.CSTVisitor):
    """Which of return/break/continue leave a try body."""

    def __init__(self) -> None:
        self.kinds: typing.Set[int] = set()
        self.loop_depth = 0

    def visit_FunctionDef(self, node) -> bool:
        return False

    def visit_ClassDef(self, node) -> bool:
        return False

    def visit_Lambda(self, node) -> bool:
        return False

    def visit_For(self, node) -> None:
        self.loop_depth += 1

    def leave_For(self, node) -> None:
        self.loop_depth -= 1

    def visit_While(self, node) -> None:
        self.loop_depth += 1

    def leave_While(self, node) -> None:
        self.loop_depth -= 1

    def visit_Return(self, node) -> None:
        self.kinds.add(TryExceptToResult.RETURN)

    def visit_Break(self, node) -> None:
        if not self.loop_depth:
            self.kinds.add(TryExceptToResult.BREAK)

    def visit_Continue(self, node) -> None:
        if not self.loop_depth:
            self.kinds.add(TryExceptToResult.CONTINUE)


class _EncodeExits(cst.CSTTransformer):
    """Inside the try-body function: return/break/continue become
    ``return (kind, value, (names...))``."""

    def __init__(self, names_tuple: cst.Tuple) -> None:
        self.names_tuple = names_tuple
        self.loop_depth = 0

    def _exit(self, kind: int, value=None) -> cst.Return:
        return cst.Return(
            value=cst.Tuple(
                [
                    cst.Element(cst.Integer(str(kind))),
                    cst.Element(value if value is not None else cst.Name("None")),
                    cst.Element(self.names_tuple),
                ]
            )
        )

    def visit_FunctionDef(self, node) -> bool:
        return False

    def visit_ClassDef(self, node) -> bool:
        return False

    def visit_Lambda(self, node) -> bool:
        return False

    def visit_For(self, node) -> None:
        self.loop_depth += 1

    def leave_For(self, original_node, updated_node):
        self.loop_depth -= 1
        return updated_node

    def visit_While(self, node) -> None:
        self.loop_depth += 1

    def leave_While(self, original_node, updated_node):
        self.loop_depth -= 1
        return updated_node

    def leave_Return(self, original_node, updated_node):
        return self._exit(TryExceptToResult.RETURN, updated_node.value)

    def leave_Break(self, original_node, updated_node):
        if self.loop_depth:
            return updated_node
        return self._exit(TryExceptToResult.BREAK)

    def leave_Continue(self, original_node, updated_node):
        if self.loop_depth:
            return updated_node
        return self._exit(TryExceptToResult.CONTINUE)


class _BeforeExits(cst.CSTTransformer):
    """Copy the finally block before every return/break/continue/raise that
    leaves a handler or else block, and turn a bare ``raise`` into a
    re-raise. (Errors raised by calls in those blocks skip the finally.)"""

    def __init__(self, finalbody, reraise: cst.BaseSmallStatement) -> None:
        self.finalbody = finalbody
        self.reraise = reraise
        self.loop_depth = 0

    def visit_FunctionDef(self, node) -> bool:
        return False

    def visit_ClassDef(self, node) -> bool:
        return False

    def visit_Lambda(self, node) -> bool:
        return False

    def visit_For(self, node) -> None:
        self.loop_depth += 1

    def leave_For(self, original_node, updated_node):
        self.loop_depth -= 1
        return updated_node

    def visit_While(self, node) -> None:
        self.loop_depth += 1

    def leave_While(self, original_node, updated_node):
        self.loop_depth -= 1
        return updated_node

    def leave_Raise(self, original_node, updated_node):
        if updated_node.exc is None:
            return self.reraise
        return updated_node

    def leave_SimpleStatementLine(self, original_node, updated_node):
        if not self.finalbody:
            return updated_node
        exits = any(
            isinstance(s, cst.Return)
            or (isinstance(s, (cst.Break, cst.Continue)) and not self.loop_depth)
            # raising: re-raise, fail(...), Error(...).unwrap()
            or s is self.reraise
            or m.matches(s, m.Expr(m.Call(func=m.Name("fail"))))
            for s in updated_node.body
        )
        if not exits:
            return updated_node
        return cst.FlattenSentinel([*self.finalbody, updated_node])


class TryExceptToResult(codemod.ContextAwareTransformer):
    """
    Larky has no try/except (all errors are fatal), but mapping over a
    ``Result`` from ``@vendor//option/result`` catches errors raised by the
    mapped function. (``Result.safe`` is not used: its wrapper function
    cannot nest, since Starlark rejects re-entering a function.)

    The try body becomes a nested function run through ``Result.map``; names it
    assigns are passed in and returned, and return/break/continue are encoded
    as ``(kind, value, names)`` so they can be re-applied outside. Handlers
    are matched with ``Result.error_is`` against the error message, which is
    "ExcName: message" for errors raised by translated code. ``except X as e``
    binds ``e`` to that message, minus the "X: " prefix.

        def f(d, k):
            try:
                v = d[k]
            except KeyError:
                v = None
            return v

    becomes:

        def f(d, k):
            def _try_1():
                v = None
                v = d[k]
                return (0, None, (v,))
            _try_1_r = Result.Ok(None).map(lambda _: _try_1())
            if _try_1_r.is_ok:
                _try_1_k, _try_1_v, (v,) = _try_1_r.unwrap()
            elif Result.error_is("^KeyError(:|$)|not found in dictionary", _try_1_r):
                v = None
            else:
                _try_1_r.unwrap()
            return v
    """

    METADATA_DEPENDENCIES = (
        ParentNodeProvider,
        cst.metadata.ScopeProvider,
        cst.metadata.PositionProvider,
    )
    FALLTHROUGH, RETURN, BREAK, CONTINUE = 0, 1, 2, 3

    def visit_Module(self, node: cst.Module) -> bool:
        self.counter = 0
        return True

    def _in_function(self, node: cst.CSTNode) -> bool:
        parent = self.get_metadata(ParentNodeProvider, node, None)
        while parent is not None:
            if isinstance(parent, cst.FunctionDef):
                return True
            parent = self.get_metadata(ParentNodeProvider, parent, None)
        return False

    def _bound_before(self, original_node: cst.Try, name: str) -> bool:
        scope = self.get_metadata(cst.metadata.ScopeProvider, original_node, None)
        if scope is None:
            return False
        start = self.get_metadata(
            cst.metadata.PositionProvider, original_node
        ).start.line
        for assignment in scope[name]:
            node = getattr(assignment, "node", None)
            if isinstance(node, cst.Param):
                return True
            try:
                pos = self.get_metadata(cst.metadata.PositionProvider, node)
            except KeyError:
                continue
            if pos.start.line < start:
                return True
        return False

    @staticmethod
    def _handler_pattern(
        handler: cst.ExceptHandler,
    ) -> typing.Tuple[typing.Optional[str], typing.List[str]]:
        """Regex matching the handled errors (None to catch everything) and
        the handled exception names."""
        if handler.type is None:
            return None, []
        types_ = (
            [e.value for e in handler.type.elements]
            if isinstance(handler.type, cst.Tuple)
            else [handler.type]
        )
        patterns, names = [], []
        for t in types_:
            name = RemoveExceptions._exc_name(t)
            if name in _CATCH_ALL:
                return None, []
            for n in _EXCEPTION_ALIASES.get(name, [name]):
                names.append(n)
                patterns.append(f"^{n}(:|$)")
                patterns.extend(_NATIVE_ERROR_PATTERNS.get(n, []))
        return "|".join(patterns), names

    def leave_Try(
        self, original_node: cst.Try, updated_node: cst.Try
    ) -> typing.Union[cst.BaseStatement, FlattenSentinel[cst.BaseStatement]]:
        if not self._in_function(original_node):
            return updated_node
        self.counter += 1
        prefix = f"_try_{self.counter}"
        fn, res, kind, val = prefix, f"{prefix}_r", f"{prefix}_k", f"{prefix}_v"

        body = list(updated_node.body.body)
        collector = _AssignedNames()
        for stmt in body:
            stmt.visit(collector)
        names = collector.names
        params = [n for n in names if self._bound_before(original_node, n)]
        unbound = [n for n in names if n not in params]
        flow = _ControlFlow()
        for stmt in body:
            stmt.visit(flow)
        exits = sorted(flow.kinds)

        names_tuple = cst.Tuple([cst.Element(cst.Name(n)) for n in names])
        encoder = _EncodeExits(names_tuple)
        fn_body = [
            cst.parse_statement(f"{n} = None") for n in unbound
        ] + [stmt.visit(encoder) for stmt in body]
        fn_body.append(
            cst.SimpleStatementLine([encoder._exit(self.FALLTHROUGH)])
        )
        try_fn = cst.FunctionDef(
            name=cst.Name(fn),
            params=cst.Parameters([cst.Param(cst.Name(n)) for n in params]),
            body=cst.IndentedBlock(fn_body),
            leading_lines=updated_node.leading_lines,
        )

        AddImportsVisitor.add_needed_import(
            self.context, "option.result", "Result"
        )
        out: typing.List[cst.BaseStatement] = [
            try_fn,
            cst.parse_statement(
                f"{res} = Result.Ok(None).map(lambda _: {fn}({', '.join(params)}))"
            ),
        ]
        if exits:
            out.append(cst.parse_statement(f"{kind} = {self.FALLTHROUGH}"))

        finalbody = (
            list(updated_node.finalbody.body.body)
            if updated_node.finalbody
            else []
        )
        reraise = cst.Expr(cst.parse_expression(f"{res}.unwrap()"))
        before_exits = _BeforeExits(finalbody, reraise)

        unpack = (
            f"{kind}, {val}, {self.module.code_for_node(names_tuple)}"
            if names
            else f"{kind}, {val}, _"
        )
        ok_body = [cst.parse_statement(f"{unpack} = {res}.unwrap()")]
        if updated_node.orelse:
            else_body = list(updated_node.orelse.body.visit(before_exits).body)
            if exits:
                ok_body.append(
                    cst.If(
                        test=cst.parse_expression(f"{kind} == {self.FALLTHROUGH}"),
                        body=cst.IndentedBlock(else_body),
                    )
                )
            else:
                ok_body.extend(else_body)

        branches = []  # (test or None, statements)
        for handler in updated_node.handlers:
            h_body = list(handler.body.visit(before_exits).body)
            pattern, exc_names = self._handler_pattern(handler)
            if handler.name:
                e = self.module.code_for_node(handler.name.name)
                bind = [cst.parse_statement(f"{e} = {res}.unwrap_err()")]
                if exc_names:
                    prefixes = ", ".join(_quote(f"{n}: ") for n in exc_names)
                    bind.append(
                        cst.parse_statement(
                            f"if {e}.startswith(({prefixes},)):\n"
                            f"    {e} = {e}.partition(': ')[2]\n"
                        )
                    )
                h_body = bind + h_body
            if pattern is None:
                branches.append((None, h_body))
                break
            test = cst.Call(
                func=cst.parse_expression("Result.error_is"),
                args=[
                    cst.Arg(cst.SimpleString(_quote(pattern))),
                    cst.Arg(cst.Name(res)),
                ],
            )
            branches.append((test, h_body))
        if not branches or branches[-1][0] is not None:
            # nothing handled this error: run finally, then re-raise
            branches.append(
                (None, finalbody + [cst.SimpleStatementLine([reraise])])
            )

        orelse = None
        for test, stmts in reversed(branches):
            block = cst.IndentedBlock(stmts)
            if test is None:
                orelse = cst.Else(body=block)
            else:
                orelse = cst.If(test=test, body=block, orelse=orelse)
        out.append(
            cst.If(
                test=cst.parse_expression(f"{res}.is_ok"),
                body=cst.IndentedBlock(ok_body),
                orelse=orelse,
            )
        )
        out.extend(finalbody)
        dispatch = {
            self.RETURN: f"return {val}",
            self.BREAK: "break",
            self.CONTINUE: "continue",
        }
        for k in exits:
            out.append(cst.parse_statement(f"if {kind} == {k}:\n    {dispatch[k]}\n"))
        return cst.FlattenSentinel(out)


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
