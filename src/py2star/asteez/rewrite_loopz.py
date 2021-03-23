import ast
import sys


def invert(node):

    inverse = {
        ast.Eq: ast.NotEq,
        ast.NotEq: ast.Eq,
        ast.Lt: ast.GtE,
        ast.LtE: ast.Gt,
        ast.Gt: ast.LtE,
        ast.GtE: ast.Lt,
        ast.Is: ast.IsNot,
        ast.IsNot: ast.Is,
        ast.In: ast.NotIn,
        ast.NotIn: ast.In,
    }

    if type(node) == ast.Compare:
        op = type(node.ops[0])
        inverse_node = ast.Compare(
            left=node.left, ops=[inverse[op]()], comparators=node.comparators
        )
    elif type(node) == ast.NameConstant and node.value in [True, False]:
        inverse_node = ast.NameConstant(value=not node.value)
    else:
        inverse_node = ast.UnaryOp(op=ast.Not(), operand=node)

    return inverse_node


class WhileToForLoop(ast.NodeTransformer):
    def visit_While(self, node):
        try:
            inverse_node = invert(node.test)
        except (AttributeError, IndexError) as e:
            print("Cannot convert this loop: ", node, e, file=sys.stderr)
            return node

        new_for = ast.For(
            target=ast.Name(id="_while_", ctx=ast.Store()),
            iter=ast.Call(
                func=ast.Name(id="range", ctx=ast.Load()),
                args=[
                    ast.Name(
                        id="_WHILE_LOOP_EMULATION_ITERATION", ctx=ast.Load()
                    )
                ],
                keywords=[],
            ),
            body=[
                ast.If(
                    test=inverse_node,
                    body=[ast.Break()],
                    orelse=[],
                )
            ]
            + node.body,
            orelse=[],
            type_comment=None,
        )
        new_for = ast.fix_missing_locations(new_for)
        return new_for
        # while pos <= finish:
        #    m = self.search(s, pos)
        print(node.test)
        print(node.body)
        print(node.orelse)

        return node

    def visit_For(self, node):
        return node
