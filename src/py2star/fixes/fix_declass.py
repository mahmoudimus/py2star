from lib2to3.fixer_base import BaseFix
from lib2to3.fixer_util import token, find_indentation


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


class FixDeclass(BaseFix):

    run_order = 7  # Fixers will be sorted by run order before execution
    # Lower numbers will be run first.

    PATTERN = """
      classdef< 'class' name=any ['(' 
           (power< 'unittest' trailer< '.' 'TestCase' > > | 'TestCase')
      ')'] ':'
         suite=suite
      >
    """

    def transform(self, node, results):
        suite = results["suite"].clone()
        # todo: handle tabs
        dedent = len(find_indentation(suite)) - len(find_indentation(node))
        dedent_suite(suite, dedent)

        # remove the first newline behind the classdef header
        first = suite.children[0]
        if first.type == token.NEWLINE:
            if len(first.value) == 1:
                del suite.children[0]
            else:
                first.value = first.value[1:]

        return suite
