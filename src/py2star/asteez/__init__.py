"""
ast - ehy-es-tee - a bunch of ast rewrites
"""
import pkgutil


def get_all_fix_names(ast_rewriter, remove_prefix=True):
    """Return a sorted list of all available fix names in the given package."""
    pkg = __import__(ast_rewriter, [], [], ["*"])
    fix_names = []
    for finder, name, ispkg in pkgutil.iter_modules(pkg.__path__):
        fix_names.append(name)
        # if name.startswith("fix_"):
        #     if remove_prefix:
        #         name = name[4:]
        #     fix_names.append(name)
    return fix_names


def get_ast_rewriters_from_package(pkg_name):
    """
    Return the fully qualified names for ast rewriters in the package pkg_name.
    """
    return [
        pkg_name + "." + fix_name
        for fix_name in get_all_fix_names(pkg_name, False)
    ]
