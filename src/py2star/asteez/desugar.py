"""
Syntactic desugaring: rewrite Python-only syntax into constructs Starlark supports.
"""
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
    str.decode(xxxx) => codecs.decode(xxxx)
    str.encode(xxxx) => codecs.encode(xxxx)

    hex() => hexlify()
    etc etc

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

    # TODO: I dont' think the below is no longer needed
    @m.call_if_inside(
        m.Call(
            func=m.Attribute(
                value=m.DoNotCare(),
                attr=m.Name("hex"),
            ),
            args=[],
        )
    )
    @m.leave(m.Call(func=m.Attribute(value=m.DoNotCare(), attr=m.Name("hex"))))
    def rewrite_hex_to_hexlify(
        self, on: "Call", un: "Call"
    ) -> "BaseExpression":
        AddImportsVisitor.add_needed_import(self.context, "codecs")
        AddImportsVisitor.add_needed_import(self.context, "binascii")
        return un.deep_replace(
            un,
            cst.parse_expression(
                f"codecs.decode(binascii.hexlify({un.func.value.value}), encoding='utf-8')"
            ),
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
        if any(
            m.matches(d.decorator, m.Name("property"))
            for d in updated_node.decorators
            if d not in kept
        ):
            result = result.with_changes(
                leading_lines=[
                    cst.EmptyLine(
                        comment=cst.Comment(
                            "# PY2LARKY: properties need --use-mutablestruct "
                            "(larky.property)"
                        )
                    )
                ]
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
