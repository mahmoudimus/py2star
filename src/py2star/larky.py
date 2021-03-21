"""
If we import this file _first_, we can run any larky script without modification
in a local python interpreter.

This is pretty critical to emulating a fantastic local repl experience.
"""
import warnings
from collections import namedtuple
from pprint import pprint
from typing import Any
import ast
import sys

MIN_PY_VERSION = 0x30900F0  # python 3.9
unparse_available = False

if sys.hexversion < MIN_PY_VERSION:
    try:
        from astunparse import unparse

        unparse_available = True
    except (ImportError, ModuleNotFoundError) as e:
        warnings.warn(
            e.msg
            + ": Either install astunparse or upgrade python to 3.9 if "
            + "you want to use unparse commands"
        )
else:
    from ast import unparse

    unparse_available = True


def struct(**kwargs):
    return namedtuple("struct", " ".join(kwargs.keys()))(**kwargs)


def _transform_import(inner_node):
    # transform load() statement into ImportFrom node
    from_name = inner_node.args[0].value
    from_name = from_name.split(".")[0]  # remove file extension
    from_name = from_name.replace("@stdlib/", "")
    from_name = from_name.replace("/", ".")  # to python syntax

    imported_names = map(
        lambda const_node: const_node.value, inner_node.args[1:]
    )
    name_tuples = [
        ast.alias(name=name, asname=None) for name in imported_names
    ]  # names are imported without alias
    as_import: ast.Import = ast.Import()
    as_import.names = name_tuples
    as_import.parent = inner_node.parent
    return as_import


class _AnalysisNodeVisitor(ast.NodeVisitor):
    def visit_Expr(self, node: ast.Expr):
        # transform python expressions containing a load() call to
        # import statements
        inner_node = node.value
        if not isinstance(inner_node.func, ast.Name):
            return self.generic_visit(node)

        func: ast.Name = inner_node.func
        if func.id == "load":
            import_node = _transform_import(inner_node)
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
    v = _AnalysisNodeVisitor()
    for n in ast.walk(p):
        for child in ast.iter_child_nodes(n):
            child.parent = n
    v.visit(p)
    ast.fix_missing_locations(p)
    if unparse_available:
        # noinspection BuiltinExec
        exec(unparse(p))
