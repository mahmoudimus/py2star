# -*- coding: utf-8 -*-
import inspect
from lib2to3.pgen2 import token

try:
    from inspect import Parameter
except ImportError:
    # Python 2
    pass
from lib2to3.fixer_util import syms
from lib2to3 import fixer_util
import re


class SelfMarker:
    pass


def get_parent_of_type(node, node_type):
    while node:
        if node.type == node_type:
            return node
        node = node.parent


def get_import_nodes(node):
    return [
        x
        for c in node.children
        for x in c.children
        if c.type == syms.simple_stmt and fixer_util.is_import(x)
    ]


def is_import(module_name):
    if fixer_util.is_import(module_name):
        return True
    # if its not,
    import_name = str(module_name)
    load_stmt = re.compile(r"load\((?:.+)?(@\w+)//(\w+)[,)]?")
    mo = load_stmt.match(import_name)
    if mo:
        return True
    return False


def _is_import_stmt(node):
    return (
        node.type == syms.simple_stmt
        and node.children
        and is_import(node.children[0])
    )


def add_larky_import(package, name, node):
    """Works like `does_tree_import` but adds an import statement
    if it was not imported."""

    root = fixer_util.find_root(node)

    if fixer_util.does_tree_import(package, name, root):
        return

    _seen_imports = set()
    # figure out where to insert the new import.  First try to find
    # the first import and then skip to the last one.
    insert_pos = offset = 0
    for idx, node in enumerate(root.children):
        if not _is_import_stmt(node):
            continue
        _seen_imports.add(str(node))
        for offset, node2 in enumerate(root.children[idx:]):
            if not _is_import_stmt(node2):
                break
            _seen_imports.add(str(node2))
        insert_pos = idx + offset
        break

    # if there are no imports where we can insert, find the docstring.
    # if that also fails, we stick to the beginning of the file
    if insert_pos == 0:
        for idx, node in enumerate(root.children):
            if (
                node.type == syms.simple_stmt
                and node.children
                and node.children[0].type == token.STRING
            ):
                insert_pos = idx + 1
                break

    ns = package
    if package is None:
        ns = "stdlib"

    import_ = fixer_util.Call(
        fixer_util.Name("load"),
        args=[
            fixer_util.String(f'"@{ns}//{name}"'),
            fixer_util.Comma(),
            fixer_util.String(f'"{name}"'),
        ],
    )

    children = [import_, fixer_util.Newline()]
    final_node = fixer_util.Node(syms.simple_stmt, children)

    # if we've already imported this thing, skip
    if str(final_node) in _seen_imports:
        return

    root.insert_child(insert_pos, final_node)


def resolve_func_args(test_func, posargs, kwargs):
    sig = inspect.signature(test_func)
    assert list(iter(sig.parameters))[0] == "self"
    posargs.insert(0, SelfMarker)
    ba = sig.bind(*posargs, **kwargs)
    ba.apply_defaults()
    args = ba.arguments
    required_args = [
        n
        for n, v in sig.parameters.items()
        if (
            v.default is Parameter.empty
            and v.kind not in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD)
        )
    ]
    assert args["self"] == SelfMarker
    assert required_args[0] == "self"
    del required_args[0], args["self"]
    required_args = [args[n] for n in required_args]

    return required_args, args


def safe_dedent(prefix, dedent_len):
    """
    Dedent the prefix of a dedent token at the start of a line.

    Non-syntactically meaningful newlines before tokens are appended to the
     prefix of the following token.

    This avoids removing the newline part of the prefix when the token
    dedents to below the given level of indentation.

    :param prefix:  prefix of a dedent token
    :param dedent_len:
    :return:
    """
    """

    """
    for i, c in enumerate(prefix):
        if c not in "\r\n":
            break
    else:
        i = len(prefix)
    return prefix[:i] + prefix[i:-dedent_len]


def dedent_suite(suite, dedent):
    """Dedent a suite in-place."""
    leaves = suite.leaves()
    for leaf in leaves:
        if leaf.type == token.NEWLINE:
            leaf = next(leaves, None)
            if leaf is None:
                return
            if leaf.type == token.INDENT:
                leaf.value = leaf.value[:-dedent]
            else:
                # this prefix will start with any duplicate newlines
                leaf.prefix = safe_dedent(leaf.prefix, dedent)
        elif leaf.type == token.INDENT:
            leaf.value = leaf.value[:-dedent]
        elif leaf.prefix.startswith(("\r", "\n")):
            leaf.prefix = leaf.prefix[:-dedent]
