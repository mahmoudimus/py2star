# -*- coding: utf-8 -*-
import inspect

try:
    from inspect import Parameter
except ImportError:
    # Python 2
    pass
from collections import OrderedDict
from lib2to3.fixer_util import syms
from lib2to3 import fixer_util
import re

class SelfMarker: pass


def get_parent_of_type(node, node_type):
    while node:
        if node.type == node_type:
            return node
        node = node.parent


def insert_import(import_stmt, nearest_parent_node, file_input):
    """This inserts an import in a very similar way as
    lib2to3.fixer_util.touch_import, but try to maintain encoding and shebang
    prefixes on top of the file when there is no import

    nearest_parent_node here is like the enclosing testcase

    """
    import_nodes = get_import_nodes(file_input)
    if import_nodes:
        last_import_stmt = import_nodes[-1].parent
        i = file_input.children.index(last_import_stmt) + 1
    # no import found, so add right before the test case
    else:
        i = file_input.children.index(nearest_parent_node)
        import_stmt.prefix = nearest_parent_node.prefix
        nearest_parent_node.prefix = ''
    file_input.insert_child(i, import_stmt)


def get_import_nodes(node):
    return [
        x for c in node.children for x in c.children
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
    #
    # fixer_util.Call(fixer_util.Name("load"), args=[
    #     fixer_util.String(f"@{ns}//{import_name}, {import_name}")
    # ])
    #
    # import_stmt = fixer_util.Node(syms.simple_stmt, [n, fixer_util.Newline()])
    #
    # # Check to see if we have already added this import.
    # for c in file_input.children:
    #     for x in c.children:
    #         if (c.type == syms.simple_stmt and
    #                 x.type == syms.power and
    #                 x.parent == import_stmt):
    #             # We have already added this import statement, so
    #             # we do not need to add it again.
    #             return


def is_import_stmt(node):
    return (node.type == syms.simple_stmt and
            node.children and
            is_import(node.children[0]))


def touch_import(package, name, node):
    """ Works like `does_tree_import` but adds an import statement
        if it was not imported. """

    root = fixer_util.find_root(node)

    if fixer_util.does_tree_import(package, name, root):
        return

    # figure out where to insert the new import.  First try to find
    # the first import and then skip to the last one.
    insert_pos = offset = 0
    for idx, node in enumerate(root.children):
        if not is_import_stmt(node):
            continue
        for offset, node2 in enumerate(root.children[idx:]):
            if not is_import_stmt(node2):
                break
        insert_pos = idx + offset
        break

    # if there are no imports where we can insert, find the docstring.
    # if that also fails, we stick to the beginning of the file
    if insert_pos == 0:
        for idx, node in enumerate(root.children):
            if (node.type == syms.simple_stmt and node.children and
               node.children[0].type == token.STRING):
                insert_pos = idx + 1
                break

    if package is None:
        import_ = Node(syms.import_name, [
            Leaf(token.NAME, "import"),
            Leaf(token.NAME, name, prefix=" ")
        ])
    else:
        import_ = FromImport(package, [Leaf(token.NAME, name, prefix=" ")])

    children = [import_, Newline()]
    root.insert_child(insert_pos, Node(syms.simple_stmt, children))


def __apply_defaults(boundargs):
    # Backport of Python 3.5 inspect.BoundArgs.apply_defaults()
    arguments = boundargs.arguments
    if not arguments:
        return
    new_arguments = []
    for name, param in boundargs.signature.parameters.items():
        try:
            new_arguments.append((name, arguments[name]))
        except KeyError:
            if param.default is not Parameter.empty:
                val = param.default
            elif param.kind is Parameter.VAR_POSITIONAL:
                val = ()
            elif param.kind is Parameter.VAR_KEYWORD:
                val = {}
            else:
                # This BoundArguments was likely produced by
                # Signature.bind_partial().
                continue
            new_arguments.append((name, val))
    boundargs.arguments = OrderedDict(new_arguments)


def resolve_func_args(test_func, posargs, kwargs):
    try:
        inspect.signature
    except AttributeError:
        # Python 2.7
        posargs.insert(0, SelfMarker)
        args = inspect.getcallargs(test_func, *posargs, **kwargs)

        assert args['self'] == SelfMarker
        argspec = inspect.getargspec(test_func)
        # if not 'Raises' in method:
        #    assert argspec.varargs is None  # unhandled case
        #    assert argspec.keywords is None  # unhandled case

        # get the required arguments
        if argspec.defaults:
            required_args = argspec.args[1:-len(argspec.defaults)]
        else:
            required_args = argspec.args[1:]
        required_args = [args[argname] for argname in required_args]

    else:
        sig = inspect.signature(test_func)
        assert (list(iter(sig.parameters))[0] == 'self')
        posargs.insert(0, SelfMarker)
        ba = sig.bind(*posargs, **kwargs)
        try:
            ba.apply_defaults
        except AttributeError:
            # Python < 3.5
            __apply_defaults(ba)
        else:
            ba.apply_defaults()
        args = ba.arguments
        required_args = [n for n, v in sig.parameters.items()
                         if (v.default is Parameter.empty and
                             v.kind not in (
                             Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD))]
        assert args['self'] == SelfMarker
        assert required_args[0] == 'self'
        del required_args[0], args['self']
        required_args = [args[n] for n in required_args]

    return required_args, args
