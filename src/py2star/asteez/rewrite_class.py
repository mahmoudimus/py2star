import libcst as cst
import typing


class ClassToFunctionRewriter(cst.CSTTransformer):
    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> typing.Union[
        cst.BaseStatement,
        cst.FlattenSentinel[cst.BaseStatement],
        cst.RemovalSentinel,
    ]:
        return updated_node.deep_replace(
            updated_node,
            cst.FunctionDef(
                name=updated_node.name,
                params=cst.Parameters(),
                body=updated_node.body,
            ),
        )
