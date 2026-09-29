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
    def visit_Module(self, node: cst.Module) -> bool:
        self.counter = 0
        return True

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

        flag = None
        if updated_node.orelse is not None:
            # user breaks skip the else; the loop condition's break does not
            self.counter += 1
            flag = f"_while_broke_{self.counter}"
            updated_node = updated_node.with_changes(
                body=updated_node.body.visit(_MarkBreaks(flag))
            )
        block: cst.IndentedBlock = updated_node.body
        new_body = list(block.body)
        if not m.matches(updated_node.test, m.Name("True")):
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
        if flag is None:
            return updated_node.deep_replace(updated_node, as_for)
        return cst.FlattenSentinel(
            [
                cst.parse_statement(f"{flag} = False").with_changes(
                    leading_lines=updated_node.leading_lines
                ),
                as_for,
                cst.If(
                    test=cst.parse_expression(f"not {flag}"),
                    body=updated_node.orelse.body,
                ),
            ]
        )


class _MarkBreaks(cst.CSTTransformer):
    """Sets ``flag = True`` before each break that exits this loop."""

    def __init__(self, flag: str) -> None:
        self.flag = flag

    def visit_For(self, node) -> bool:
        return False

    def visit_While(self, node) -> bool:
        return False

    def visit_FunctionDef(self, node) -> bool:
        return False

    def visit_ClassDef(self, node) -> bool:
        return False

    def visit_Lambda(self, node) -> bool:
        return False

    def _mark(self, updated_node):
        body = []
        for stmt in updated_node.body:
            if isinstance(stmt, cst.Break):
                body.append(
                    cst.Assign(
                        targets=[cst.AssignTarget(cst.Name(self.flag))],
                        value=cst.Name("True"),
                    )
                )
            body.append(stmt)
        return updated_node.with_changes(body=body)

    def leave_SimpleStatementLine(self, original_node, updated_node):
        return self._mark(updated_node)

    def leave_SimpleStatementSuite(self, original_node, updated_node):
        return self._mark(updated_node)


class ForElseToFlag(codemod.ContextAwareTransformer):
    """
    Starlark has no for/else:

        for x in xs:
            if x:
                break
        else:
            print("no break")

    becomes:

        _broke_1 = False
        for x in xs:
            if x:
                _broke_1 = True; break
        if not _broke_1:
            print("no break")
    """

    def visit_Module(self, node: cst.Module) -> bool:
        self.counter = 0
        return True

    def leave_For(
        self, original_node: cst.For, updated_node: cst.For
    ) -> typing.Union[cst.BaseStatement, cst.FlattenSentinel]:
        if updated_node.orelse is None:
            return updated_node
        self.counter += 1
        flag = f"_broke_{self.counter}"
        body = updated_node.body.visit(_MarkBreaks(flag))
        return cst.FlattenSentinel(
            [
                cst.parse_statement(f"{flag} = False").with_changes(
                    leading_lines=updated_node.leading_lines
                ),
                updated_node.with_changes(
                    body=body, orelse=None, leading_lines=[]
                ),
                cst.If(
                    test=cst.parse_expression(f"not {flag}"),
                    body=updated_node.orelse.body,
                ),
            ]
        )
