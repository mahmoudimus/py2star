from lib2to3.fixer_base import BaseFix
from lib2to3.fixer_util import token, find_indentation

"""
Node(classdef, 
     [Leaf(1, 'class'), 
      Leaf(1, 'TestAssertEqual'), 
      Leaf(7, '('), 
      Leaf(1, 'TestCase'), 
      Leaf(8, ')'), 
      Leaf(11, ':'), 
      Node(suite, [
          Leaf(4, '\n'), 
          Leaf(5, '    '), 
          Node(funcdef, [
              Leaf(1, 'def'), 
              Leaf(1, 'test_you'), ...
          ]), 
          Leaf(6, '')])])
"""


def safe_dedent(s, dedent):
    """
    Dedent the prefix of a dedent token at the start of a line.
    Non-syntactically meaningful newlines before tokens are appended to the prefix
    of the following token, so this avoids removing the newline part of the prefix
    when the token dedents to below the given level of indentation.
    """
    for i, c in enumerate(s):
        if c not in "\r\n":
            break
    else:
        i = len(s)
    return s[:i] + s[i:-dedent]


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

    PATTERN = """
      classdef< 'class' name=any ['(' 
           (power< 'unittest' trailer< '.' 'TestCase' > > | 'TestCase')
      ')'] ':'
         suite=suite
      >
    """

    def dedent(self, suite, dedent):
        self.line_num = suite.get_lineno()
        for kid in suite.leaves():
            if kid.type in (token.INDENT, token.DEDENT):
                self.line_num = kid.get_lineno()
                # todo: handle tabs
                kid.value = kid.value[dedent:]
                self.current_indent = kid.value
            elif kid.get_lineno() != self.line_num:
                # todo: handle tabs
                if len(kid.prefix) > len(self.current_indent):
                    kid.prefix = self.current_indent

    def transform(self, node, results):
        suite = results['suite'].clone()
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
