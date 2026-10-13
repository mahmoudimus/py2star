"""
Syntactic desugaring: rewrite Python-only syntax into constructs Starlark supports.
"""
import codecs
import functools
from typing import Union
import warnings

import typing

import libcst as cst
from libcst import (
    BaseExpression,
    BaseStatement,
    Call,
    ConcatenatedString,
    FlattenSentinel,
    RemovalSentinel,
    SimpleStatementLine,
    codemod,
    ensure_type,
)
import libcst.matchers as m
from libcst.codemod.visitors import AddImportsVisitor
from libcst.metadata import (
    ParentNodeProvider,
    QualifiedNameProvider,
    QualifiedNameSource,
    ScopeProvider,
)


class RewriteImplicitStringConcat(codemod.ContextAwareTransformer):
    """
    a = (" "
         " ")
    ==>
    a = (" " +
    " ")
    """

    METADATA_DEPENDENCIES = (ParentNodeProvider,)

    def leave_ConcatenatedString(
        self, original: "ConcatenatedString", updated: "ConcatenatedString"
    ) -> "BaseExpression":

        # We want to avoid replacing the leaf nodes because there might
        # be a logic error if it's a multi-line string:
        #
        #    a = ("foo"
        #        "boo"
        #        "zoo")
        #
        #    should be transformed to:
        #
        #    a = ("foo" +
        #        "boo" +
        #        "zoo")
        #
        # but it will fail if we only replace the leaf node (i.e.:
        #
        #
        #    a = "foo"   <--- logic error!
        #        ("boo" +
        #        "zoo")
        #
        # so we have to find the parent node first, then traverse down
        # the tree and replace all ConcatenatedString with the binary
        # operations ("foo" + "boo" + "zoo"), etc.
        parent = self.get_metadata(ParentNodeProvider, original)
        if isinstance(parent, (cst.ConcatenatedString,)):
            return updated  # it's not the parent node, so return.

        # ok this is the parent node.
        ws_between = updated.whitespace_between
        curr = updated

        # take the left most string
        # z = [curr.left]
        z = []
        # and traverse the right node creating binary operations
        while (
            curr is not None
            and hasattr(curr, "right")
            and isinstance(curr.right, (cst.ConcatenatedString,))
        ):
            z.append(curr.left)
            curr = curr.right
        z.append(curr.left)
        z = z[::-1]

        node = functools.reduce(
            lambda right, left: cst.BinaryOperation(
                left=left,
                operator=cst.Add(whitespace_after=ws_between),
                right=right,
            ),
            z,
            curr.right,
        )
        return node.with_changes(
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
        )


class SwapByteStringPrefixes(codemod.ContextAwareTransformer):
    @m.call_if_inside(m.SimpleString(value=m.MatchRegex(r"""^br["'].+?""")))
    def leave_SimpleString(
        self, original_node: "SimpleString", updated_node: "SimpleString"
    ) -> "BaseExpression":
        return updated_node.with_changes(
            value=updated_node.value.replace("br", "rb", 1)
        )


class SubMethodsWithLibraryCallsInstead(codemod.ContextAwareTransformer):
    """
    str.encode(xxxx) => codecs.encode(xxxx)
    codecs.encode(b, "hex") => binascii.hexlify(b)

    bytes.hex() is left as is: Larky supports it natively.

    if not m.matches(
        updated_node,
        m.Call(
            func=m.Attribute(
                value=m.DoNotCare(),
                attr=m.OneOf(
                    m.Name(value="encode"), m.Name(value="decode")
                ),
            ),
            args=m.DoNotCare(),
        ),
    ):
        return updated_node
    """

    _HEX_CODECS = ('"hex"', "'hex'", '"hex_codec"', "'hex_codec'")
    METADATA_DEPENDENCIES = (
        QualifiedNameProvider,
        ScopeProvider,
        ParentNodeProvider,
    )

    @staticmethod
    def _is_str_value(node: cst.BaseExpression) -> bool:
        """An expression that always produces a str."""
        if isinstance(node, (cst.SimpleString, cst.ConcatenatedString)):
            value = node.evaluated_value
            return isinstance(value, str)
        if isinstance(node, cst.FormattedString):
            return True
        if m.matches(node, m.Call(func=m.Name("str") | m.Name("repr") | m.Name("format"))):
            return True
        if m.matches(
            node,
            m.Call(
                func=m.Attribute(
                    value=m.SimpleString() | m.ConcatenatedString(),
                    attr=m.Name("format") | m.Name("join"),
                )
            ),
        ):
            return SubMethodsWithLibraryCallsInstead._is_str_value(node.func.value)
        if isinstance(node, cst.BinaryOperation) and isinstance(
            node.operator, (cst.Add, cst.Modulo)
        ):
            # str + x and str % x are str (or raise)
            return SubMethodsWithLibraryCallsInstead._is_str_value(node.left)
        return False

    _NOT_STR = (
        cst.Integer,
        cst.Float,
        cst.Imaginary,
        cst.List,
        cst.Tuple,
        cst.Dict,
        cst.Set,
        cst.ListComp,
        cst.DictComp,
        cst.SetComp,
    )

    def _receiver_type(self, receiver: cst.BaseExpression) -> str:
        """"str", "not str" or "unknown", from the assignments that can reach
        a name (both branches of an if, loop reassignments, parameters)."""
        if self._is_str_value(receiver):
            return "str"
        if not isinstance(receiver, cst.Name):
            return "unknown"
        referents = self._referents(receiver)
        if not referents:
            return "unknown"
        kinds = {self._assignment_type(ref) for ref in referents}
        if "not str" in kinds:
            return "not str"
        return "str" if kinds == {"str"} else "unknown"

    def _referents(self, name: cst.Name) -> list:
        """The assignments that can reach this use of a name."""
        scope = self.get_metadata(ScopeProvider, name, None)
        if scope is None:
            return []
        return [
            ref
            for access in scope.accesses[name]
            if access.node is name
            for ref in access.referents
        ]

    def _assignment_type(self, ref) -> str:
        node = ref.node
        if isinstance(node, (cst.Import, cst.ImportFrom, cst.ClassDef, cst.FunctionDef)):
            return "not str"
        if isinstance(node, cst.Param):
            annotated_str = m.matches(
                node, m.Param(annotation=m.Annotation(m.Name("str")))
            )
            return "str" if annotated_str else "unknown"
        parent = self.get_metadata(ParentNodeProvider, node, None)
        if isinstance(parent, cst.AnnAssign):
            if m.matches(parent.annotation, m.Annotation(m.Name("str"))):
                return "str"
            value = parent.value
        elif isinstance(parent, cst.AssignTarget):
            value = self.get_metadata(ParentNodeProvider, parent).value
        elif isinstance(parent, cst.AugAssign):
            value = parent.value
        else:
            # for-loop targets, tuple unpacking, with ... as, etc.
            return "unknown"
        if value is None:
            return "unknown"
        if self._is_str_value(value):
            return "str"
        if isinstance(value, self._NOT_STR) or m.matches(
            value, m.SimpleString(value=m.MatchRegex(r"(?is)r?br?['\"].*"))
        ):
            return "not str"
        if m.matches(value, m.Call(func=m.Name())) and any(
            isinstance(r.node, cst.ClassDef) for r in self._referents(value.func)
        ):
            # an instance of a class defined here
            return "not str"
        return "unknown"

    def _is_str_encode(self, call: "Call") -> bool:
        """Whether x.encode(...) is str.encode(encoding, errors).

        Receivers are typed from the assignments that can reach them. A
        known str accepts any str.encode-shaped call; a known non-str (an
        import, a class, a number, a list...) never matches. Otherwise this
        goes by shape: not a call on an imported module or name
        (jwt.encode, base64...), at most the two str.encode arguments, and
        literal arguments that are a real codec and error handler. Anything
        else is left as is, so it fails loudly in Larky instead of calling
        the wrong function.
        """
        receiver = call.func.value
        args = call.args
        shaped = len(args) <= 2 and not any(a.star for a in args) and not any(
            a.keyword and a.keyword.value not in ("encoding", "errors")
            for a in args
        )
        kind = self._receiver_type(receiver)
        if kind == "not str" or not shaped:
            return False
        if kind == "str":
            return True
        base = receiver
        while isinstance(base, cst.Attribute):
            base = base.value
        if isinstance(base, cst.Name) and any(
            q.source == QualifiedNameSource.IMPORT
            for q in self.get_metadata(QualifiedNameProvider, base, set())
        ):
            return False
        args = call.args
        if len(args) > 2 or any(a.star for a in args):
            return False
        if any(
            a.keyword and a.keyword.value not in ("encoding", "errors")
            for a in args
        ):
            return False
        for i, a in enumerate(args):
            kind = a.keyword.value if a.keyword else ("encoding", "errors")[i]
            literal = (
                a.value.evaluated_value
                if isinstance(a.value, (cst.SimpleString, cst.ConcatenatedString))
                else None
            )
            if literal is None:
                if not a.keyword:
                    # a positional non-literal: not recognizably str.encode
                    return False
                continue
            if kind == "encoding" and not self._is_codec(literal):
                return False
            if kind == "errors" and literal not in self._ERROR_HANDLERS:
                return False
        return True

    _ERROR_HANDLERS = frozenset(
        (
            "strict",
            "ignore",
            "replace",
            "backslashreplace",
            "xmlcharrefreplace",
            "namereplace",
            "surrogateescape",
            "surrogatepass",
        )
    )

    @staticmethod
    def _is_codec(name) -> bool:
        try:
            codecs.lookup(name)
        except (LookupError, TypeError):
            return False
        return True

    def leave_Call(self, original_node: "Call", updated_node: "Call"):
        func = updated_node.func
        if not isinstance(func, cst.Attribute):
            return updated_node
        method = func.attr.value
        if m.matches(func.value, m.Name("codecs")):
            # codecs.encode(b, "hex") => binascii.hexlify(b)
            args = updated_node.args
            if (
                method in ("encode", "decode")
                and len(args) >= 2
                and m.matches(args[1].value, m.SimpleString())
                and args[1].value.value in self._HEX_CODECS
            ):
                AddImportsVisitor.add_needed_import(self.context, "binascii")
                fn = "hexlify" if method == "encode" else "unhexlify"
                return cst.Call(
                    func=cst.Attribute(cst.Name("binascii"), cst.Name(fn)),
                    args=[args[0].with_changes(comma=cst.MaybeSentinel.DEFAULT)],
                )
            return updated_node
        if method != "encode":
            # ignore bytes.decode() since we support that now.
            return updated_node
        if not self._is_str_encode(original_node):
            # e.g. jwt.encode(claims, key, algorithm=...): not str.encode
            return updated_node
        # s.encode(encoding, errors) => codecs.encode(s, encoding=..., errors=...)
        AddImportsVisitor.add_needed_import(self.context, "codecs")
        eq = cst.AssignEqual(
            whitespace_before=cst.SimpleWhitespace(""),
            whitespace_after=cst.SimpleWhitespace(""),
        )
        kwargs = {"encoding": cst.SimpleString('"utf-8"')}
        for keyword, arg in zip(("encoding", "errors"), updated_node.args):
            name = arg.keyword.value if arg.keyword else keyword
            kwargs[name] = arg.value
        return cst.Call(
            func=cst.Attribute(value=cst.Name("codecs"), attr=func.attr),
            args=[cst.Arg(value=func.value)]
            + [
                cst.Arg(value=v, keyword=cst.Name(k), equal=eq)
                for k, v in kwargs.items()
            ],
        )


class UnpackTargetAssignments(codemod.ContextAwareTransformer):
    """
    a = b = "xyz"

    to:

    a = "xyz"
    b = a
    """

    @m.call_if_inside(
        m.SimpleStatementLine(
            body=[
                m.Assign(
                    targets=[m.AtLeastN(n=2, matcher=m.AssignTarget())],
                    value=m.DoNotCare(),
                    # value=m.OneOf(m.SimpleString(), m.Name()),
                )
            ]
        )
    )
    def leave_SimpleStatementLine(
        self,
        original_node: "SimpleStatementLine",
        updated_node: "SimpleStatementLine",
    ) -> Union[
        "BaseStatement", FlattenSentinel["BaseStatement"], RemovalSentinel
    ]:
        assign_stmt = updated_node.body[0]
        stmts = [
            cst.SimpleStatementLine(
                body=[
                    cst.Assign(
                        targets=[
                            cst.AssignTarget(
                                target=assign_stmt.targets[0].target
                            ),
                        ],
                        value=assign_stmt.value,
                    ),
                ]
            )
        ]
        # idx here starts at 0, so it is -1 from current pointer of targets
        for idx, t in enumerate(assign_stmt.targets[1:]):
            stmts.append(
                cst.SimpleStatementLine(
                    body=[
                        cst.Assign(
                            targets=[
                                cst.AssignTarget(target=t.target),
                            ],
                            value=assign_stmt.targets[0].target,
                        ),
                    ]
                )
            )
        return cst.FlattenSentinel(stmts)


class DesugarDecorators(codemod.ContextAwareTransformer):
    """
    @decorator
    def foo(a, b):
        return True

    is the same as:

    def foo(a, b):
        return True
    foo = decorator(foo)

    """

    def __init__(self, context, exclude_decorators=None, noop=False) -> None:
        super(DesugarDecorators, self).__init__(context)
        self.excluded = exclude_decorators if exclude_decorators else []
        self.noop = noop

    @m.call_if_inside(m.ClassDef(decorators=[m.AtLeastN(n=1)]))
    def leave_ClassDef(
        self, original_node: "ClassDef", updated_node: "ClassDef"
    ) -> Union[
        "BaseStatement", FlattenSentinel["BaseStatement"], RemovalSentinel
    ]:
        warnings.warn(
            "Decorators are not supported in Starlark. "
            "Py2Star does not support transforming them either. "
            "Please do this manually (if this transform is run *before* the "
            "declass transform*)"
        )
        return updated_node

    @m.call_if_inside(m.FunctionDef(decorators=[m.AtLeastN(n=1)]))
    def leave_FunctionDef(
        self, original_node: "FunctionDef", updated_node: "FunctionDef"
    ) -> Union[
        "BaseStatement", FlattenSentinel["BaseStatement"], RemovalSentinel
    ]:
        fn = ensure_type(updated_node.name, cst.Name)
        fn_name = fn
        kept = []
        for d in reversed(updated_node.decorators):
            if self._is_excluded(d.decorator):
                if m.matches(
                    d.decorator, m.Name("property") | m.Attribute(attr=m.Name("setter"))
                ):
                    # left for the class rewriter (larky.property)
                    kept.insert(0, d)
                # staticmethod/classmethod are meaningless in starlark
                continue
            fn = cst.Call(d.decorator, args=[cst.Arg(fn)])
        if fn is fn_name:
            return updated_node.with_changes(decorators=kept)
        result = cst.SimpleStatementLine(
            body=[cst.Assign(targets=[cst.AssignTarget(target=fn_name)], value=fn)]
        )
        undecorated = updated_node.with_changes(decorators=kept)
        return cst.FlattenSentinel([undecorated, result])

    def _is_excluded(self, decorator: cst.BaseExpression) -> bool:
        if isinstance(decorator, cst.Name):
            return decorator.value in self.excluded
        # @x.setter / @x.getter / @x.deleter
        return (
            isinstance(decorator, cst.Attribute)
            and f".{decorator.attr.value}" in self.excluded
        )


class DesugarBuiltinOperators(codemod.ContextAwareTransformer):
    """
    - ** to pow
    """

    @m.call_if_inside(m.BinaryOperation(operator=m.Power()))
    def leave_BinaryOperation(
        self, original_node: "BinaryOperation", updated_node: "BinaryOperation"
    ) -> "BaseExpression":
        return cst.Call(
            func=cst.Name(value="pow"),
            args=[
                cst.Arg(updated_node.left),
                cst.Arg(updated_node.right),
            ],
        )


class DesugarSetSyntax(codemod.ContextAwareTransformer):
    """
    {1, 2} => Set([1, 2])  (Starlark has no set type; see @stdlib//sets)
    """

    def leave_Set(self, original_node: cst.Set, updated_node: cst.Set):
        AddImportsVisitor.add_needed_import(self.context, "sets", "Set")
        return cst.Call(
            func=cst.Name(value="Set"),
            args=[cst.Arg(value=cst.List(elements=updated_node.elements))],
            lpar=updated_node.lpar,
            rpar=updated_node.rpar,
        )

    def leave_SetComp(self, original_node: cst.SetComp, updated_node: cst.SetComp):
        AddImportsVisitor.add_needed_import(self.context, "sets", "Set")
        return cst.Call(
            func=cst.Name(value="Set"),
            args=[
                cst.Arg(
                    value=cst.ListComp(
                        elt=updated_node.elt, for_in=updated_node.for_in
                    )
                )
            ],
        )


class RewriteBuiltins(codemod.ContextAwareTransformer):
    """
    Python builtins that Starlark lacks:

        sum(xs)                => builtins.sum(xs)
        map(f, xs)             => builtins.map(f, xs)
        filter(f, xs)          => [_x for _x in xs if f(_x)]
        set(xs), frozenset(xs) => Set(xs)
        issubclass(a, b)       => larky.is_subclass(a, b)
        dict.fromkeys(xs, v)   => larky.dicts.fromkeys(xs, v)
        bytearray(n)           => bytearray(b"\\x00" * n)  (n: int literal or len())

    Only names that resolve to the builtin are rewritten.
    """

    METADATA_DEPENDENCIES = (QualifiedNameProvider,)

    def _is_builtin(self, node: cst.BaseExpression, name: str) -> bool:
        if not m.matches(node, m.Name(name)):
            return False
        return any(
            q.source == QualifiedNameSource.BUILTIN
            for q in self.get_metadata(QualifiedNameProvider, node, set())
        )

    @staticmethod
    def _is_int_expr(node: cst.BaseExpression) -> bool:
        if isinstance(node, cst.Integer) or m.matches(
            node, m.Call(func=m.Name("len"))
        ):
            return True
        if isinstance(node, cst.BinaryOperation):
            return RewriteBuiltins._is_int_expr(
                node.left
            ) or RewriteBuiltins._is_int_expr(node.right)
        return False

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call):
        func, args = original_node.func, updated_node.args
        if self._is_builtin(func, "sum") or self._is_builtin(func, "map"):
            AddImportsVisitor.add_needed_import(self.context, "builtins")
            return updated_node.with_changes(
                func=cst.Attribute(cst.Name("builtins"), updated_node.func)
            )
        if self._is_builtin(func, "filter") and len(args) == 2:
            item = cst.Name("_x")
            predicate = args[0].value
            if not isinstance(predicate, (cst.Name, cst.Attribute)):
                # (lambda v: ...)(_x)
                predicate = predicate.with_changes(
                    lpar=[cst.LeftParen()], rpar=[cst.RightParen()]
                )
            cond = (
                item
                if m.matches(predicate, m.Name("None"))
                else cst.Call(func=predicate, args=[cst.Arg(item)])
            )
            return cst.ListComp(
                elt=item,
                for_in=cst.CompFor(
                    target=item, iter=args[1].value, ifs=[cst.CompIf(cond)]
                ),
            )
        if self._is_builtin(func, "set") or self._is_builtin(func, "frozenset"):
            AddImportsVisitor.add_needed_import(self.context, "sets", "Set")
            return updated_node.with_changes(func=cst.Name("Set"))
        if self._is_builtin(func, "issubclass"):
            AddImportsVisitor.add_needed_import(self.context, "larky")
            return updated_node.with_changes(
                func=cst.parse_expression("larky.is_subclass")
            )
        if (
            m.matches(func, m.Attribute(value=m.Name("dict"), attr=m.Name("fromkeys")))
            and self._is_builtin(func.value, "dict")
        ):
            AddImportsVisitor.add_needed_import(self.context, "larky")
            return updated_node.with_changes(
                func=cst.parse_expression("larky.dicts.fromkeys")
            )
        if (
            self._is_builtin(func, "bytearray")
            and len(args) == 1
            and not args[0].keyword
            and self._is_int_expr(args[0].value)
        ):
            size = args[0].value
            if isinstance(size, cst.BinaryOperation):
                size = size.with_changes(
                    lpar=[cst.LeftParen()], rpar=[cst.RightParen()]
                )
            return updated_node.with_changes(
                args=[
                    cst.Arg(
                        cst.BinaryOperation(
                            left=cst.SimpleString('b"\\x00"'),
                            operator=cst.Multiply(),
                            right=size,
                        )
                    )
                ]
            )
        return updated_node


def _slice_bounds(sub: cst.Subscript):
    """(lower, upper) of a step-less slice subscript, else None."""
    if len(sub.slice) != 1 or not isinstance(sub.slice[0].slice, cst.Slice):
        return None
    sl = sub.slice[0].slice
    if sl.step is not None:
        return None
    return sl.lower, sl.upper


def _mutate_slice(
    module: cst.Module,
    seq: cst.BaseExpression,
    lower,
    upper,
    tag: str,
    new: typing.Optional[cst.BaseExpression] = None,
) -> typing.List[cst.BaseStatement]:
    """In-place ``del seq[lower:upper]`` / ``seq[lower:upper] = new``.

    ``len(seq[:i])`` normalizes a bound the way slicing does (None,
    negative, past the end).
    """
    code = module.code_for_node
    s = code(seq)
    lo, hi = f"_lo_{tag}", f"_hi_{tag}"
    stmts = []
    if new is not None:
        # evaluate first: it may read seq
        stmts.append(f"_new_{tag} = list({code(new)})")
    stmts.append(f"{lo} = len({s}[:{code(lower)}])" if lower else f"{lo} = 0")
    stmts.append(
        f"{hi} = max({lo}, len({s}[:{code(upper)}]))" if upper else f"{hi} = len({s})"
    )
    stmts.append(f"for _ in range({hi} - {lo}):\n    {s}.pop({lo})\n")
    if new is not None:
        stmts.append(
            f"for _i, _v in enumerate(_new_{tag}):\n"
            f"    {s}.insert({lo} + _i, _v)\n"
        )
    return [cst.parse_statement(st) for st in stmts]


class RewriteSliceAssignment(codemod.ContextAwareTransformer):
    """
    Starlark cannot assign to a slice; do it in place:

        seq[i:j] = other

    becomes:

        _new_1 = list(other)
        _lo_1 = len(seq[:i])
        _hi_1 = max(_lo_1, len(seq[:j]))
        for _ in range(_hi_1 - _lo_1):
            seq.pop(_lo_1)
        for _i, _v in enumerate(_new_1):
            seq.insert(_lo_1 + _i, _v)
    """

    def visit_Module(self, node: cst.Module) -> bool:
        self.counter = 0
        return True

    def leave_SimpleStatementLine(self, original_node, updated_node):
        if len(updated_node.body) != 1 or not m.matches(
            updated_node.body[0],
            m.Assign(targets=[m.AssignTarget(m.Subscript())]),
        ):
            return updated_node
        assign = updated_node.body[0]
        target = assign.targets[0].target
        bounds = _slice_bounds(target)
        if bounds is None:
            return updated_node
        if m.matches(
            assign.value,
            m.SimpleString(value=m.MatchRegex(r"(?is)r?br?['\"].*"))
            | m.Call(func=m.Name("bytes") | m.Name("bytearray")),
        ):
            # Larky bytearrays hold bytes items; there is no in-place
            # equivalent, so leave it for a manual port.
            return updated_node.with_changes(
                leading_lines=[
                    *updated_node.leading_lines,
                    cst.EmptyLine(
                        comment=cst.Comment(
                            "# PY2LARKY: slice assignment of bytes is not supported"
                        )
                    ),
                ]
            )
        self.counter += 1
        stmts = _mutate_slice(
            self.module, target.value, *bounds, f"s{self.counter}", assign.value
        )
        stmts[0] = stmts[0].with_changes(leading_lines=updated_node.leading_lines)
        return cst.FlattenSentinel(stmts)


class RemoveDelKeyword(codemod.ContextAwareTransformer):
    """
    Starlark has no ``del``:

        del d[k]         => d.pop(k)
        del seq[i:j]     => in-place pops (see RewriteSliceAssignment)
        del a, b[0]      => one statement per target
        del x, del obj.x => commented out (names cannot be unbound)
    """

    def visit_Module(self, node: cst.Module) -> bool:
        self.counter = 0
        return True

    def _del_target(self, target) -> typing.List[cst.BaseStatement]:
        if isinstance(target, cst.Subscript):
            bounds = _slice_bounds(target)
            if bounds is not None:
                self.counter += 1
                return _mutate_slice(
                    self.module, target.value, *bounds, f"d{self.counter}"
                )
            if len(target.slice) == 1 and isinstance(
                target.slice[0].slice, cst.Index
            ):
                # dict.pop(k) / list.pop(i) raise like del does. (Larky's
                # operator.delitem always fails for dicts.)
                return [
                    cst.SimpleStatementLine(
                        [
                            cst.Expr(
                                cst.Call(
                                    func=cst.Attribute(
                                        target.value, cst.Name("pop")
                                    ),
                                    args=[cst.Arg(target.slice[0].slice.value)],
                                )
                            )
                        ]
                    )
                ]
        return [
            cst.SimpleStatementLine(
                [cst.Del(target=target)],
                leading_lines=[
                    cst.EmptyLine(
                        comment=cst.Comment(
                            "# PY2LARKY: unsupported del (extended slice)"
                        )
                    )
                ],
            )
        ]

    def leave_SimpleStatementLine(
        self,
        original_node: "SimpleStatementLine",
        updated_node: "SimpleStatementLine",
    ) -> Union["BaseStatement", FlattenSentinel["BaseStatement"], RemovalSentinel]:
        if len(updated_node.body) != 1 or not isinstance(
            updated_node.body[0], cst.Del
        ):
            return updated_node
        target = updated_node.body[0].target
        targets = (
            [e.value for e in target.elements]
            if isinstance(target, (cst.Tuple, cst.List))
            and not (target.lpar or isinstance(target, cst.List))
            else [target]
        )
        if all(isinstance(t, (cst.Name, cst.Attribute)) for t in targets):
            # del self.xxxx: attributes and names cannot be removed
            commented = "# del " + ", ".join(
                self.module.code_for_node(t) for t in targets
            )
            return updated_node.with_changes(
                body=[cst.Pass()],
                leading_lines=[
                    *updated_node.leading_lines,
                    cst.EmptyLine(comment=cst.Comment(value=commented)),
                ],
            )
        stmts = [s for t in targets for s in self._del_target(t)]
        stmts[0] = stmts[0].with_changes(
            leading_lines=[*updated_node.leading_lines, *stmts[0].leading_lines]
        )
        return cst.FlattenSentinel(stmts)
