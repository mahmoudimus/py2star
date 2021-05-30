from typing import Union

import libcst
import libcst as cst
from libcst import (
    BaseSmallStatement,
    BaseStatement,
    FlattenSentinel,
    Raise,
    RemovalSentinel,
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

    def leave_ClassDef(
        self, original_node: "ClassDef", updated_node: "ClassDef"
    ) -> Union[
        "BaseStatement", FlattenSentinel["BaseStatement"], RemovalSentinel
    ]:
        return updated_node

    def leave_FunctionDef(
        self, original_node: "FunctionDef", updated_node: "FunctionDef"
    ) -> Union[
        "BaseStatement", FlattenSentinel["BaseStatement"], RemovalSentinel
    ]:
        return updated_node


class DecodeEncodeViaCodecs(codemod.ContextAwareTransformer):
    """
    str.decode(xxxx) => codecs.decode(xxxx)
    str.encode(xxxx) => codecs.encode(xxxx)
    """

    pass


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
                    value=m.SimpleString(),
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
                            value=assign_stmt.targets[idx].target,
                        ),
                    ]
                )
            )
        return cst.FlattenSentinel(stmts)


class DesugarBuiltinOperators(codemod.ContextAwareTransformer):
    """
    - ** to pow
    - X @ Y = operator.matmul(x,y)..
    """

    def leave_BinaryOperation(
        self, original_node: "BinaryOperation", updated_node: "BinaryOperation"
    ) -> "BaseExpression":
        return updated_node


class DesugarSetSyntax(codemod.ContextAwareTransformer):
    """
        In [3]: ast.dump(ast.parse("set([1, 2])""))
    Out[3]: "Module(body=[Expr(value=Call(func=Name(id='set', ctx=Load()), args=[List(e
    lts=[Constant(value=1, kind=None), Constant(value=2, kind=None)], ctx=Load())], key
    words=[]))], type_ignores=[])"

    In [4]: ast.dump(ast.parse("set(1, 2)"))
    Out[4]: "Module(body=[Expr(value=Call(func=Name(id='set', ctx=Load()), args=[Consta
    nt(value=1, kind=None), Constant(value=2, kind=None)], keywords=[]))], type_ignores
    =[])"
    """

    def leave_Set(
        self, original_node: "Set", updated_node: "Set"
    ) -> "BaseExpression":
        return updated_node

    def leave_SetComp(
        self, original_node: "SetComp", updated_node: "SetComp"
    ) -> "BaseExpression":
        return updated_node


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

    def leave_Raise(
        self, original_node: "Raise", updated_node: "Raise"
    ) -> Union[
        "BaseSmallStatement",
        FlattenSentinel["BaseSmallStatement"],
        RemovalSentinel,
    ]:
        exc_name = ensure_type(updated_node.exc, cst.Call)
        args2 = []
        for a in exc_name.args:
            if isinstance(a.value, cst.BinaryOperation):
                newval = cst.parse_expression(
                    f'"{exc_name.func.value}: {a.value.left.raw_value}"'
                )
                args2.append(
                    a.with_changes(value=a.value.with_changes(left=newval))
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
