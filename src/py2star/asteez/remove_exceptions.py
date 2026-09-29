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

    def _on_exc_attribute(
        self,
        original_node: "Raise",
        updated_node: "Raise",
    ) -> Union[
        "BaseSmallStatement",
        FlattenSentinel["BaseSmallStatement"],
        RemovalSentinel,
    ]:
        exc = ensure_type(updated_node.exc, cst.Attribute)
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

        if m.matches(updated_node, m.Raise(exc=m.Attribute())):
            return self._on_exc_attribute(original_node, updated_node)

        if m.matches(updated_node, m.Raise(exc=None)):
            # just naked raise, just replace w/ return
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

        _config = self.context.scratch.get("config")
        if _config and _config.get("use_error_not_fail", False):
            rval = cst.Call(func=cst.Name(value=f"Error"), args=args2)
            upd = cst.Return(value=rval)
        else:
            rval = cst.Call(func=cst.Name(value=f"fail"), args=args2)
            upd = cst.Expr(value=rval)
            # upd = cst.SimpleStatementLine(body=[cst.Expr(value=rval)])

        AddImportsVisitor.add_needed_import(
            self.context, "option.result", "Error"
        )

        return cst.FlattenSentinel([upd])
        # return cst.FlattenSentinel([upd])

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
