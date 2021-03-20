import ast
from itertools import tee


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

    def visit_Compare(self, node):
        if not self._is_chained_compare(node):
            return node

        ands = []
        for left, right, op in zip(pairwise(node.comparators), node.ops):
            item = ast.Compare(
                left=left,
                right=right,
                ops=[op],
            )
            ands.append(item)

        print(ands)  # join these d00ds with an AND
        return node

    @staticmethod
    def _is_chained_compare(node):
        """
        Detects usage of a chained sequence of comparisons.
        Example:
            1 < x < y <= 5
        """
        return len(node.ops) > 1
