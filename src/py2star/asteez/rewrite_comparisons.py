import typing
from functools import reduce
from itertools import chain, tee
from typing import Union

import libcst as cst
from libcst import (
    BaseStatement,
    FlattenSentinel,
    RemovalSentinel,
    codemod,
    matchers as m,
)
from libcst.codemod import CodemodContext, ContextAwareTransformer


def pairwise(iterable):
    """s -> (s0,s1), (s1,s2), (s2, s3), ..."""
    a, b = tee(iterable)
    next(b, None)
    return zip(a, b)


class UnchainComparison(codemod.ContextAwareTransformer):
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
        self, original_node: cst.Comparison, updated_node: cst.Comparison
    ) -> typing.Union[cst.BaseExpression, cst.RemovalSentinel]:
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
            item = cst.Comparison(
                left,
                comparisons=[cst.ComparisonTarget(op, right)],
                lpar=[cst.LeftParen()],
                rpar=[cst.RightParen()],
            )
            ands.append(item)

        def build_comparison_tree(left_node, right_node):
            return cst.BooleanOperation(
                left=left_node, operator=cst.And(), right=right_node
            )

        # noinspection PyTypeChecker
        new_node: cst.BooleanOperation = reduce(
            build_comparison_tree, ands[1:], ands[0]
        )
        return updated_node.deep_replace(updated_node, new_node)

    @staticmethod
    def _is_chained_compare(node: cst.Comparison):
        """
        Detects usage of a chained sequence of comparisons.
        Example:
            1 < x < y <= 5
        """
        return len(node.comparisons) > 1


class IsComparisonTransformer(codemod.ContextAwareTransformer):
    def __init__(self, context=None):
        context = context if context else CodemodContext()
        super(IsComparisonTransformer, self).__init__(context)

    @m.leave(m.ComparisonTarget(comparator=m.DoNotCare(), operator=m.Is()))
    def convert_is_to_equals(
        self, _, updated_node: cst.ComparisonTarget
    ) -> Union[cst.ComparisonTarget, cst.RemovalSentinel]:
        original_op = cst.ensure_type(updated_node.operator, cst.Is)

        return updated_node.with_changes(
            operator=cst.Equal(
                whitespace_after=original_op.whitespace_after,
                whitespace_before=original_op.whitespace_before,
            )
        )

    @m.leave(m.ComparisonTarget(comparator=m.DoNotCare(), operator=m.IsNot()))
    def convert_is_not_to_not_equals(
        self, _, updated_node: cst.ComparisonTarget
    ) -> Union[cst.ComparisonTarget, cst.RemovalSentinel]:
        original_op = cst.ensure_type(updated_node.operator, cst.IsNot)

        return updated_node.with_changes(
            operator=cst.NotEqual(
                whitespace_after=original_op.whitespace_after,
                whitespace_before=original_op.whitespace_before,
            )
        )


class RemoveIfNameEqualsMain(codemod.ContextAwareTransformer):
    def __init__(self, context):
        super(RemoveIfNameEqualsMain, self).__init__(context)

    @m.call_if_inside(
        m.If(
            test=m.Comparison(
                left=m.Name("__name__"),
                comparisons=[
                    m.ComparisonTarget(
                        comparator=m.OneOf(
                            m.SimpleString("'__main__'"),
                            m.SimpleString('"__main__"'),
                        )
                    )
                ],
            )
        )
    )
    def leave_If(
        self, original_node: "If", updated_node: "If"
    ) -> Union[
        "BaseStatement", FlattenSentinel["BaseStatement"], RemovalSentinel
    ]:
        return cst.RemoveFromParent()
