import ast
import sys
from pprint import pprint
from typing import Any

MIN_PY_VERSION = 0x30900F0  # python 3.9
if sys.hexversion < MIN_PY_VERSION:
    try:
        from astunparse import unparse
    except (ImportError, ModuleNotFoundError) as e:
        raise ImportError(
            e.msg + ": Either install astunparse or upgrade python to 3.9"
        )
else:
    from ast import unparse


def transform_import(node):
    # transform load() statement into ImportFrom node
    from_name = node.args[0].value
    from_name = from_name.split(".")[0]  # remove file extension
    from_name = from_name.replace("@stdlib/", "")
    from_name = from_name.replace("/", ".")  # to python syntax

    imported_names = map(lambda const_node: const_node.value, node.args[1:])
    name_tuples = [
        ast.alias(name=name, asname=None) for name in imported_names
    ]  # names are imported without alias
    as_import: ast.Import = ast.Import()
    as_import.names = name_tuples
    as_import.parent = node.parent
    return as_import


class AnalysisNodeVisitor(ast.NodeVisitor):
    def visit_Expr(self, node: ast.Expr):
        # transform python expressions containing a load() call to import statements
        inner_node = node.value
        if not isinstance(inner_node.func, ast.Name):
            return self.generic_visit(node)

        func: ast.Name = inner_node.func
        if func.id == "load":
            import_node = transform_import(inner_node)
            node.value = import_node
            return import_node
        return self.generic_visit(node)


if __name__ == "__main__":
    p = ast.parse(
        r"""     
load("@stdlib/json", "json")
print(json.loads('{"one": 1, "two": 2}'))
print(json.loads('"\\ud83d\\ude39\\ud83d\\udc8d"'))
"""
    )
    v = AnalysisNodeVisitor()
    for node in ast.walk(p):
        for child in ast.iter_child_nodes(node):
            child.parent = node
    v.visit(p)
    ast.fix_missing_locations(p)
    exec(unparse(p))