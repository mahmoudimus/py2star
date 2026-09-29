"""
Syntactic desugaring: rewrite Python-only syntax into constructs Starlark supports.
"""
import functools
from typing import Union
import warnings

import libcst as cst
from libcst import (
    BaseExpression,
    BaseSmallStatement,
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
from libcst.codemod import CodemodContext
from libcst.codemod.visitors import AddImportsVisitor
from libcst.metadata import ParentNodeProvider


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

    @m.call_if_inside(
        m.Call(
            func=m.Attribute(
                value=m.DoNotCare(),
                attr=m.OneOf(
                    m.Name(value="encode")
                    # ignore bytes.decode() since we support that now.
                    # , m.Name(value="decode")
                ),
            ),
            # todo: respect the `aggressive-codecs` cli parameter
            args=m.DoNotCare(),
        )
    )
    @m.leave(m.Call(func=m.Attribute(value=m.DoNotCare(), attr=m.DoNotCare())))
    def rewrite_encode_decode(self, on: "Call", un: "Call") -> "BaseExpression":
        AddImportsVisitor.add_needed_import(self.context, "codecs")
        encoding = cst.SimpleString(value='"utf-8"')
        if un.args:
            encoding = un.args[0].value
        expr = cst.Call(
            func=cst.Attribute(
                value=cst.Name(
                    value="codecs",
                ),
                attr=un.func.attr,
            ),
            args=[
                cst.Arg(value=un.func.value),
                cst.Arg(
                    value=encoding,
                    keyword=cst.Name("encoding"),
                    equal=cst.AssignEqual(
                        whitespace_before=cst.SimpleWhitespace(""),
                        whitespace_after=cst.SimpleWhitespace(""),
                    ),
                ),
            ],
        )
        return un.deep_replace(un, expr)

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
        for d in reversed(updated_node.decorators):
            # if decorator does not have arguments
            if not m.matches(d.decorator, m.TypeOf(m.Call)):
                # skip if it is not staticmethod or classmethod since these are
                # meaningless in starlark
                if d.decorator.value in self.excluded:
                    continue
            fn = cst.Call(d.decorator, args=[cst.Arg(fn)])
        result = cst.Assign(
            targets=[cst.AssignTarget(target=fn_name)], value=fn
        )
        undecorated = updated_node.with_changes(decorators=[])
        return cst.FlattenSentinel(
            [undecorated, cst.SimpleStatementLine(body=[result])]
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
    @m.call_if_inside(m.Assign(value=m.Set(elements=m.DoNotCare())))
    def leave_Assign(
        self, original_node: "Assign", updated_node: "Assign"
    ) -> Union[
        "BaseSmallStatement",
        FlattenSentinel["BaseSmallStatement"],
        RemovalSentinel,
    ]:
        """
        x = {1,2} => x = set([1,2])
        """
        return self.convert_set_expr_to_fn(original_node, updated_node)

    @m.call_if_inside(m.Expr(value=m.Set(elements=m.DoNotCare())))
    def leave_Expr(
        self, original_node: "Expr", updated_node: "Expr"
    ) -> Union[
        "BaseSmallStatement",
        FlattenSentinel["BaseSmallStatement"],
        RemovalSentinel,
    ]:
        """
        {1,2} => set([1,2])
        """
        return self.convert_set_expr_to_fn(original_node, updated_node)

    def convert_set_expr_to_fn(
        self,
        original_node: Union["Assign", "Expr"],
        updated_node: Union["Assign", "Expr"],
    ) -> Union[
        "BaseSmallStatement",
        FlattenSentinel["BaseSmallStatement"],
        RemovalSentinel,
    ]:
        AddImportsVisitor.add_needed_import(self.context, "sets", "Set")
        return updated_node.with_changes(
            value=cst.Call(
                func=cst.Name(value="Set"),
                args=[
                    cst.Arg(
                        value=cst.List(elements=updated_node.value.elements)
                    )
                ],
            )
        )


class RemoveDelKeyword(codemod.ContextAwareTransformer):
    METADATA_DEPENDENCIES = (
        cst.metadata.ParentNodeProvider,
        cst.metadata.ScopeProvider,
        cst.metadata.PositionProvider,
    )

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)
        self.names = []

    @m.call_if_inside(m.SimpleStatementLine(body=[m.Del(target=m.DoNotCare())]))
    def leave_SimpleStatementLine(
        self,
        original_node: "SimpleStatementLine",
        updated_node: "SimpleStatementLine",
    ) -> Union["BaseStatement", FlattenSentinel["BaseStatement"], RemovalSentinel]:
        # del self.xxxx
        _attr = m.Del(
            target=m.Tuple(
                elements=[
                    m.AtLeastN(
                        n=1,
                        matcher=m.Element(value=m.Attribute(value=m.DoNotCare())),
                    )
                ]
            )
        )
        if updated_node.body and m.matches(updated_node.body[0], _attr):
            commented = "# del " + "".join(
                self.module.code_for_node(t)
                for t in updated_node.body[0].target.elements
            )
            un = updated_node.with_changes(
                body=[cst.Pass()],
                leading_lines=[
                    *updated_node.leading_lines,
                    cst.EmptyLine(comment=cst.Comment(value=commented)),
                ],
            )
            return un
        # del a[b]
        _delitem = m.Del(
            target=m.Subscript(
                value=m.OneOf(
                    m.Name(value=m.DoNotCare()),
                    m.Attribute(value=m.DoNotCare()),
                )
            )
        )
        if m.matches(updated_node.body[0], _delitem):
            # operator.delitem(a, b, /)
            # Same as del a[b].
            AddImportsVisitor.add_needed_import(self.context, "operator")
            subscript = updated_node.body[0].target.slice[0].slice
            value = getattr(subscript, "value", None)
            if not value and isinstance(subscript, cst.Slice):
                value = cst.parse_expression(
                    "slice(" +
                        subscript.lower.value + 
                        "," +
                        subscript.upper.value +
                        ("," + subscript.step.value if subscript.step else "") +
                        ")")
            un = updated_node.deep_replace(
                updated_node,
                cst.helpers.parse_template_statement(
                    # "operator.delitem({value}.{attr}, {slice})",
                    "operator.delitem({value}, {slice})",
                    config=self.module.config_for_parsing,
                    value=updated_node.body[0].target.value,
                    # attr=updated_node.target.value.attr,
                    slice=value,
                ),
            )
            return un
        return updated_node
