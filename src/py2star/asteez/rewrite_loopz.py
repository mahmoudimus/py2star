import libcst as ast
import sys

import typing

from birdseye import eye
from libcst import codemod


def invert(node):

    inverse = {
        ast.Equal: ast.NotEqual,
        ast.NotEqual: ast.Equal,
        ast.LessThan: ast.GreaterThanEqual,
        ast.LessThanEqual: ast.GreaterThan,
        ast.GreaterThan: ast.LessThanEqual,
        ast.GreaterThanEqual: ast.LessThan,
        ast.Is: ast.IsNot,
        ast.IsNot: ast.Is,
        ast.In: ast.NotIn,
        ast.NotIn: ast.In,
    }

    if type(node) == ast.Comparison:
        op = type(node.comparisons[0].operator)
        inverse_node = ast.Comparison(
            left=node.left,
            comparisons=[
                ast.ComparisonTarget(
                    inverse[op](), node.comparisons[0].comparator
                )
            ],
        )
    elif type(node) == ast.Name and node.value in [True, False]:
        inverse_node = ast.Name(value=f"{not node.value}")
    else:
        inverse_node = ast.UnaryOperation(operator=ast.Not(), expression=node)

    return inverse_node


class WhileToForLoop(codemod.VisitorBasedCodemodCommand):
    @eye
    def leave_While(
        self, original_node: ast.While, updated_node: ast.While
    ) -> typing.Union[ast.BaseStatement, ast.RemovalSentinel]:
        try:
            inverse_node = invert(updated_node.test)
        except (AttributeError, IndexError) as e:
            print(
                "Cannot convert this loop: ", updated_node, e, file=sys.stderr
            )
            return updated_node

        block: ast.IndentedBlock = updated_node.body
        new_body = list(block.body)
        new_body.insert(
            0,
            ast.If(
                test=inverse_node,
                body=ast.IndentedBlock(
                    body=[ast.SimpleStatementLine(body=[ast.Break()])]
                ),
                orelse=None,
            ),
        )
        as_for = ast.For(
            target=ast.Name(value="_while_"),
            iter=ast.Call(
                func=ast.Name(value="range"),
                args=[
                    ast.Arg(value=ast.Name("_WHILE_LOOP_EMULATION_ITERATION"))
                ],
            ),
            body=ast.IndentedBlock(
                body=new_body,
                footer=block.footer,
                header=block.header,
            ),
            orelse=None,
        )
        return updated_node.deep_replace(updated_node, as_for)
