import sys
import typing

import libcst as cst
import libcst.matchers as m
from libcst import codemod
from libcst.codemod.visitors import AddImportsVisitor


def invert(node):

    inverse = {
        cst.Equal: cst.NotEqual,
        cst.NotEqual: cst.Equal,
        cst.LessThan: cst.GreaterThanEqual,
        cst.LessThanEqual: cst.GreaterThan,
        cst.GreaterThan: cst.LessThanEqual,
        cst.GreaterThanEqual: cst.LessThan,
        cst.Is: cst.IsNot,
        cst.IsNot: cst.Is,
        cst.In: cst.NotIn,
        cst.NotIn: cst.In,
    }

    if type(node) == cst.Comparison:
        op = type(node.comparisons[0].operator)
        inverse_node = cst.Comparison(
            left=node.left,
            comparisons=[
                cst.ComparisonTarget(
                    inverse[op](), node.comparisons[0].comparator
                )
            ],
        )
    elif type(node) == cst.Name and node.value in [True, False]:
        inverse_node = cst.Name(value=f"{not node.value}")
    else:
        inverse_node = cst.UnaryOperation(operator=cst.Not(), expression=node)

    return inverse_node


class WhileToForLoop(codemod.ContextAwareTransformer):
    def leave_While(
        self, original_node: cst.While, updated_node: cst.While
    ) -> typing.Union[
        cst.BaseStatement,
        cst.FlattenSentinel["cst.BaseStatement"],
        cst.RemovalSentinel,
    ]:
        try:
            inverse_node = invert(updated_node.test)
        except (AttributeError, IndexError) as e:
            print(
                "Cannot convert this loop: ", updated_node, e, file=sys.stderr
            )
            return updated_node

        block: cst.IndentedBlock = updated_node.body
        new_body = list(block.body)
        new_body.insert(
            0,
            cst.If(
                test=inverse_node,
                body=cst.IndentedBlock(
                    body=[cst.SimpleStatementLine(body=[cst.Break()])]
                ),
                orelse=None,
            ),
        )
        as_for = cst.For(
            target=cst.Name(value="_while_"),
            iter=cst.Call(
                func=cst.Name(value="range"),
                args=[
                    cst.Arg(value=cst.Name("WHILE_LOOP_EMULATION_ITERATION"))
                ],
            ),
            body=cst.IndentedBlock(
                body=new_body,
                footer=block.footer,
                header=block.header,
            ),
            orelse=None,
        )
        AddImportsVisitor.add_needed_import(
            self.context,
            "larky",
            "larky",
        )
        AddImportsVisitor.add_needed_import(
            self.context,
            "larky",
            "WHILE_LOOP_EMULATION_ITERATION",
        )
        return updated_node.deep_replace(updated_node, as_for)
