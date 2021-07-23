import typing
from typing import Union
import warnings

import libcst as cst
from libcst import (
    BaseExpression,
    BaseSmallStatement,
    BaseStatement,
    Call,
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

    EXCLUDED = (
        "staticmethod",
        "classmethod",
    )

    def __init__(self, context, exclude_decorators=None, noop=False) -> None:
        super(DesugarDecorators, self).__init__(context)
        self.excluded = (
            exclude_decorators if exclude_decorators else self.EXCLUDED
        )
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
                attr=m.OneOf(m.Name(value="encode"), m.Name(value="decode")),
            ),
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

        left = updated.left
        right = updated.right
        ws_between = updated.whitespace_between

        # ctx = original
        # current = cst.BinaryOperation(
        #     left=ctx.left,
        #     operator=cst.Add(whitespace_after=ctx.whitespace_between),
        #     right=ctx.right,
        # )
        # while isinstance(ctx, (cst.ConcatenatedString,)):
        #     ctx = self.get_metadata(ParentNodeProvider, ctx)
        #
        #
        # node = ctx.deep_replace(ctx, current)
        # return node
        # print(cst.parse_module("").code_for_node(node))

        return updated.deep_replace(
            updated,
            cst.BinaryOperation(
                left=left,
                operator=cst.Add(whitespace_after=ws_between),
                right=right,
            )
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


class RemoveExceptions(codemod.ContextAwareTransformer):
    def __init__(self, context=None):
        context = context if context else CodemodContext()
        super(RemoveExceptions, self).__init__(context)
        self._update_parent = False

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

    def leave_SimpleStatementLine(
        self,
        original_node: "SimpleStatementLine",
        updated_node: "SimpleStatementLine",
    ) -> Union[
        "BaseStatement", FlattenSentinel["BaseStatement"], RemovalSentinel
    ]:
        if not self._update_parent:
            return updated_node
        if not m.matches(
            original_node,
            m.SimpleStatementLine(body=[m.OneOf(m.Raise(exc=m.Name()))]),
        ):
            return updated_node

        return updated_node.with_changes(
            leading_lines=[
                cst.EmptyLine(
                    comment=cst.Comment(
                        value=f"# PY2LARKY: pay attention to this!"
                    )
                ),
                *updated_node.leading_lines,
            ]
        )

    def _on_exc_name(
        self,
        original_node: "Raise",
        updated_node: "Raise",
    ) -> Union[
        "BaseSmallStatement",
        FlattenSentinel["BaseSmallStatement"],
        RemovalSentinel,
    ]:
        exc = ensure_type(updated_node.exc, cst.Name)
        self._update_parent = True
        return cst.FlattenSentinel([cst.Return(value=exc)])

    # @m.call_if_inside(m.Raise(exc=m.Call()))
    def leave_Raise(
        self, original_node: "Raise", updated_node: "Raise"
    ) -> Union[
        "BaseSmallStatement",
        FlattenSentinel["BaseSmallStatement"],
        RemovalSentinel,
    ]:
        if m.matches(updated_node, m.Raise(exc=m.Name())):
            return self._on_exc_name(original_node, updated_node)

        if m.matches(updated_node, m.Raise(exc=None)):
            # just naked raise, just repalce w/ return
            return cst.FlattenSentinel([cst.Return(value=None)])

        assert m.matches(updated_node, m.Raise(exc=m.Call()))
        exc_name = ensure_type(updated_node.exc, cst.Call)
        args2 = []
        for a in exc_name.args:
            if isinstance(a.value, cst.BinaryOperation):
                # s = self.module.code_for_node(a.value.left)
                # newval = cst.parse_expression(
                #     s.replace('"', f'"{exc_name.func.value}: ', 1)
                # )
                # newval = cst.parse_expression(
                #     f'"{exc_name.func.value}: {a.value.left.raw_value}"'
                # )
                # args2.append(
                #     a.with_changes(value=a.value.with_changes(left=newval))
                # )
                newval = cst.parse_expression(f'"{exc_name.func.value}: "')
                args2.append(
                    a.with_changes(
                        value=cst.BinaryOperation(
                            left=newval, operator=cst.Add(), right=a.value
                        )
                    )
                )
                # args2.append(
                #     a.with_changes(
                #         value=a.value.with_changes(
                #             left=cst.SimpleString(
                #                 value=f'"{exc_name.func.value}: {a.value.left.raw_value}"'
                #             )
                #         )
                #     )
                # )
            elif isinstance(a.value, cst.SimpleString):
                args2.append(
                    a.with_changes(
                        value=cst.SimpleString(
                            value=f'"{exc_name.func.value}: {a.value.raw_value}"'
                        )
                    )
                )

        rval = cst.Call(func=cst.Name(value=f"Error"), args=args2)
        AddImportsVisitor.add_needed_import(
            self.context, "option.result", "Error"
        )
        upd = cst.Return(value=rval)
        return cst.FlattenSentinel([upd])

        # return Result.Error("JWKError: " + args)

        # return updated_node.with_changes(
        #     body=[
        #         cst.Call(
        #
        #         )
        #     ]
        # )


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
