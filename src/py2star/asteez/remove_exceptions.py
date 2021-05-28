from typing import Union

import libcst
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
from libcst.codemod import CodemodContext
from libcst.codemod.visitors import AddImportsVisitor
from libcst.metadata import ParentNodeProvider


class RemoveExceptions(codemod.VisitorBasedCodemodCommand):
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
        exc_name = ensure_type(updated_node.exc, libcst.Call)
        args2 = []
        for a in exc_name.args:
            if isinstance(a.value, libcst.BinaryOperation):
                newval = libcst.parse_expression(
                    f'"{exc_name.func.value}: {a.value.left.raw_value}"'
                )
                args2.append(
                    a.with_changes(value=a.value.with_changes(left=newval))
                )
                # args2.append(
                #     a.with_changes(
                #         value=a.value.with_changes(
                #             left=libcst.SimpleString(
                #                 value=f'"{exc_name.func.value}: {a.value.left.raw_value}"'
                #             )
                #         )
                #     )
                # )
            elif isinstance(a.value, libcst.SimpleString):
                args2.append(
                    a.with_changes(
                        value=libcst.SimpleString(
                            value=f'"{exc_name.func.value}: {a.value.raw_value}"'
                        )
                    )
                )

        rval = libcst.Call(func=libcst.Name(value=f"Error"), args=args2)
        AddImportsVisitor.add_needed_import(
            self.context, "option.result", "Error"
        )
        upd = libcst.Return(value=rval)
        return libcst.FlattenSentinel([upd])

        # return Result.Error("JWKError: " + args)

        # return updated_node.with_changes(
        #     body=[
        #         libcst.Call(
        #
        #         )
        #     ]
        # )
