from typing import Union

from libcst import BaseStatement, FlattenSentinel, RemovalSentinel, Try, codemod
from libcst.codemod import CodemodContext


class RemoveExceptions(codemod.VisitorBasedCodemodCommand):
    def __init__(self, context=None):
        context = context if context else CodemodContext()
        super(RemoveExceptions, self).__init__(context)

    DESCRIPTION = "Removes exceptions."

    def leave_Try(
        self, original_node: "Try", updated_node: "Try"
    ) -> Union[
        "BaseStatement", FlattenSentinel["BaseStatement"], RemovalSentinel
    ]:
        pass
