import typing
from functools import reduce
from itertools import chain, tee

import libcst as ast
from libcst import codemod


def pairwise(iterable):
    """s -> (s0,s1), (s1,s2), (s2, s3), ..."""
    a, b = tee(iterable)
    next(b, None)
    return zip(a, b)


class UnchainComparison(codemod.VisitorBasedCodemodCommand):
    """
    ChainedCompare

      Corresponds to a chained sequence of comparison
      expressions.

      Example:
          1 < x <= y < 10
      Becomes:
          (1 < x) and (x <= y) and (y < 10)

    """

    def leave_Comparison(
        self, original_node: ast.Comparison, updated_node: ast.Comparison
    ) -> typing.Union[ast.BaseExpression, ast.RemovalSentinel]:
        if not self._is_chained_compare(updated_node):
            return updated_node

        ands = []
        for (left, right), op in zip(
            # returns (1, x), (x, y), (y, ..)..
            pairwise(
                chain(
                    [updated_node.left],
                    (c.comparator for c in updated_node.comparisons),
                )
            ),
            (c.operator for c in updated_node.comparisons),
        ):
            item = ast.Comparison(
                left,
                comparisons=[ast.ComparisonTarget(op, right)],
                lpar=[ast.LeftParen()],
                rpar=[ast.RightParen()],
            )
            ands.append(item)

        def build_comparison_tree(left_node, right_node):
            return ast.BooleanOperation(
                left=left_node, operator=ast.And(), right=right_node
            )

        # noinspection PyTypeChecker
        new_node: ast.BooleanOperation = reduce(
            build_comparison_tree, ands[1:], ands[0]
        )
        return updated_node.deep_replace(updated_node, new_node)

    @staticmethod
    def _is_chained_compare(node: ast.Comparison):
        """
        Detects usage of a chained sequence of comparisons.
        Example:
            1 < x < y <= 5
        """
        return len(node.comparisons) > 1
