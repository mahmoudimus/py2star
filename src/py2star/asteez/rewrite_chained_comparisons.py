import ast
from itertools import chain, tee

from birdseye import eye


def pairwise(iterable):
    """s -> (s0,s1), (s1,s2), (s2, s3), ..."""
    a, b = tee(iterable)
    next(b, None)
    return zip(a, b)


class UnchainComparison(ast.NodeTransformer):
    """
    ChainedCompare

      Corresponds to a chained sequence of comparison
      expressions.

      Example:
          1 < x <= y < 10
      Becomes:
          (1 < x) and (x <= y) and (y < 10)

    """

    @eye
    def visit_Compare(self, node):
        if not self._is_chained_compare(node):
            return node

        ands = []
        for (left, right), op in zip(
            # returns (1, x), (x, y), (y, ..)..
            pairwise(chain([node.left], node.comparators)),
            node.ops,
        ):
            item = ast.Compare(
                left=left,
                comparators=[right],
                ops=[op],
            )
            ands.append(item)

        new_node = ast.BoolOp(op=ast.And(), values=ands)
        new_node = ast.copy_location(new_node, old_node=node)
        new_node = ast.fix_missing_locations(new_node)
        return new_node

    @staticmethod
    def _is_chained_compare(node):
        """
        Detects usage of a chained sequence of comparisons.
        Example:
            1 < x < y <= 5
        """
        return len(node.ops) > 1
