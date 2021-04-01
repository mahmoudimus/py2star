import libcst as cst
import typing


class ClassToFunctionRewriter(cst.CSTTransformer):
    def __init__(self, namespace_defs=False):
        super(ClassToFunctionRewriter, self).__init__()
        self.namespace_defs = namespace_defs
        self.class_name = ""

    def visit_ClassDef(self, node: "ClassDef") -> typing.Optional[bool]:
        self.class_name = node.name.value

    def leave_FunctionDef(
        self, original_node: "FunctionDef", updated_node: "FunctionDef"
    ) -> typing.Union[
        "BaseStatement",
        cst.FlattenSentinel["BaseStatement"],
        cst.RemovalSentinel,
    ]:
        if not self.namespace_defs:
            return updated_node
        return updated_node.with_changes(
            name=cst.Name(f"{self.class_name}_{updated_node.name.value}")
        )

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
