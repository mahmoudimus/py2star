import libcst as ast
from libcst import codemod


def get_name(attribute_node):
    if isinstance(attribute_node, str):
        return attribute_node
    if isinstance(attribute_node, ast.Name):
        return attribute_node.id
    if isinstance(attribute_node, ast.Call):
        return get_name(attribute_node.func)
    if not hasattr(attribute_node, "value"):
        return attribute_node.id

    if not hasattr(attribute_node, "attr"):
        attr = str(attribute_node)
    else:
        attr = attribute_node.attr
    return get_name(attribute_node.value) + "." + attr


class AttributeRenamer(codemod.VisitorBasedCodemodCommand):
    def __init__(self, context, substitutes):
        super(AttributeRenamer, self).__init__(context)
        self.substitutes = substitutes

    def visit_Name(self, node):
        return self.visit_Attribute(node)

    def visit_Attribute(self, node):
        name = get_name(node)
        if name in self.substitutes:
            return self.substitutes[name]
        return node


class FunctionParameterStripper(ast.NodeTransformer):
    def __init__(self, params):
        self.params = params

    def visit_arguments(self, node: ast.arguments):
        node.args = [arg for arg in node.args if arg.arg not in self.params]
        return node


class AttributeGetter(ast.NodeTransformer):
    """
    AttributeGetter(["self"]): self.foo => foo
    """

    def __init__(self, namespace):
        self.namespace = namespace

    def get_value(self, node):
        name = get_name(node)
        attributes = name.split(".")
        if attributes[0] in self.namespace:
            # obj = self.namespace[attributes.pop(0)]
            # return ast.parse(repr(obj)).body[0].value
            obj = ".".join(attributes[1:])
            return ast.Name(obj, ctx=ast.Load())

    def visit_Attribute(self, node):
        val = self.get_value(node)
        return val if val is not None else node
