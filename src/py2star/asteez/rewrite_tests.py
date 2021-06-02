from typing import Union
import warnings

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
                if d.decorator.value in ("staticmethod", "classmethod"):
                    continue
            fn = cst.Call(d.decorator, args=[cst.Arg(fn)])
        result = cst.Assign(
            targets=[cst.AssignTarget(target=fn_name)], value=fn
        )
        undecorated = updated_node.with_changes(decorators=[])
        return cst.FlattenSentinel(
            [undecorated, cst.SimpleStatementLine(body=[result])]
        )


class SubMethodsWithLibraryCallsInstead(codemod.ContextAwareTransformer):
    """
    str.decode(xxxx) => codecs.decode(xxxx)
    str.encode(xxxx) => codecs.encode(xxxx)

    hex() => hexlify()
    etc etc
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

    @m.call_if_inside(m.Raise(exc=m.Call()))
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
