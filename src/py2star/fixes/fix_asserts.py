# -*- coding: utf-8 -*-
"""
fix_self_assert - lib2to3 fix for replacing assertXXX() method calls
by their pytest equivalent.
"""
#
# Copyright 2015-2019 by Hartmut Goebel <h.goebel@crazy-compilers.com>
#
# This file is part of unittest2pytest.
#
# unittest2pytest is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#

__author__ = "Hartmut Goebel <h.goebel@crazy-compilers.com>"
__copyright__ = "Copyright 2015-2019 by Hartmut Goebel"
__licence__ = "GNU General Public License version 3 or later (GPLv3+)"

import re
import unittest
from functools import partial
from lib2to3.fixer_base import BaseFix
from lib2to3.fixer_util import (
    Comma, Name, Call, Node, Leaf, ArgList,
    Newline, KeywordArg, find_indentation,
    String, Number, syms, token,
    LParen, RParen, Attr,
    does_tree_import, is_import, parenthesize)

from py2star import utils

TEMPLATE_PATTERN = re.compile('[\1\2]|[^\1\2]+')


def add_import(import_name, node, ns="stdlib"):
    suite = utils.get_parent_of_type(node, syms.suite)
    test_case = suite
    while test_case.parent.type != syms.file_input:
        test_case = test_case.parent
    file_input = test_case.parent

    if does_tree_import(None, import_name, node):
        return

    n = Call(Name("load"), args=[
                String(f'"@{ns}//{import_name}"'),
                Comma(),
                String(f'"{import_name}"')
        ])
    import_stmt = Node(syms.simple_stmt, [n, Newline()])

    # Check to see if we have already added this import.
    for c in file_input.children:
        for x in c.children:
            if (c.type == syms.simple_stmt and
                    x.type == syms.power and
                    x.parent == import_stmt):
                # We have already added this import statement, so
                # we do not need to add it again.
                return
    utils.insert_import(import_stmt, test_case, file_input)


def CompOp(op, left, right, kws):
    left = parenthesize_expression(left)
    right = parenthesize_expression(right)

    left.prefix = ""
    if '\n' not in right.prefix:
        right.prefix = ""

    # trailer< '.' 'assert_that' > trailer< '(' '1' ')' >
    _left_asserts = Call(Name("assert_that"), args=[left])
    new = Node(
        syms.power,
        # trailer< '.' 'is_equal_to' > trailer< '(' '2' ')' > >
        Attr(_left_asserts, Name('is_equal_to')) +
        [Node(syms.trailer,[LParen(), right, RParen()])]
    )
    return new

    # Trailer('.', 'assert_that') Trailer(('(', '1', ')'), )
    # return Node(syms.trailer, )
    #return Node(syms.comparison, (left, op, right), prefix=" ")


def UnaryOp(prefix, postfix, value, kws):
    if prefix or postfix:
        value = parenthesize_expression(value)

    kids = []
    if prefix:
        kids.append(Name(prefix, prefix=" "))
    value.prefix = " "
    kids.append(value)
    if postfix:
        kids.append(Name(postfix, prefix=" "))
    return Node(syms.test, kids, prefix=" ")


# These symbols have lower precedence than the CompOps we use and thus
# need to be parenthesized. For details see
# https://docs.python.org/3/reference/expressions.html#operator-precedence
_NEEDS_PARENTHESIS = [
    syms.test,  # if – else
    syms.or_test,
    syms.and_test,
    syms.not_test,
    syms.comparison,
]


def parenthesize_expression(value):
    if value.type in _NEEDS_PARENTHESIS:
        parenthesized = parenthesize(value.clone())
        parenthesized.prefix = parenthesized.children[1].prefix
        parenthesized.children[1].prefix = ''
        value = parenthesized
    return value


def fill_template(template, *args):
    parts = TEMPLATE_PATTERN.findall(template)
    kids = []
    for p in parts:
        if p == '':
            continue
        elif p in '\1\2\3\4\5':
            p = args[ord(p) - 1]
            p.prefix = ''
        else:
            p = Name(p)
        kids.append(p.clone())
    return kids


def DualOp(template, first, second, kws):
    kids = fill_template(template, first, second)
    return Node(syms.test, kids, prefix=" ")


def SequenceEqual(left, right, kws):
    if 'seq_type' in kws:
        # :todo: implement `assert isinstance(xx, seq_type)`
        pass
    return CompOp('==', left, right, kws)


def AlmostOp(places_op, delta_op, first, second, kws):
    first.prefix = ""
    second.prefix = ""
    first = parenthesize_expression(first)
    second = parenthesize_expression(second)
    abs_op = Call(Name('abs'),
                  [Node(syms.factor, [first, Name('-'), second])])
    if kws.get('delta', None) is not None:
        # delta
        return CompOp(delta_op, abs_op, kws['delta'], {})
    else:
        # `7` is the default in unittest.TestCase.asserAlmostEqual
        places = kws['places'] or Number(7)
        places.prefix = " "
        round_op = Call(Name('round'), (abs_op, Comma(), places))
        return CompOp(places_op, round_op, Number(0), {})


def RaisesOp(context, exceptionClass, indent, kws, arglist, node):
    exceptionClass.prefix = ""
    args = [exceptionClass]
    # Add match keyword arg to with statement if an expected regex was provided.
    # In py27 the keyword is `expected_regexp`, in py3 is `expected_regex`
    if 'expected_regex' in kws or 'expected_regexp' in kws:
        expected_regex = kws.get('expected_regex',
                                 kws.get('expected_regexp')).clone()
        expected_regex.prefix = ''
        args.append(String(', '))
        args.append(
            KeywordArg(Name('match'), expected_regex))
    with_item = Call(Name(context), args)
    with_item.prefix = " "
    args = []
    arglist = [a.clone() for a in arglist.children[4:]]
    if arglist:
        arglist[0].prefix = ""

    func = None

    # :fixme: this uses hardcoded parameter names, which may change
    if 'callableObj' in kws:
        func = kws['callableObj']
    elif 'callable_obj' in kws:
        func = kws['callable_obj']
    elif kws['args']:  # any arguments assigned to `*args`
        func = kws['args'][0]
    else:
        func = None

    if func is None:
        # Context manager
        return Node(syms.with_stmt, [with_item])

    if func.type == syms.lambdef:
        suite = func.children[-1].clone()
    else:
        # TODO: Newlines within arguments are not handled yet.
        # If argment prefix contains a newline, all whitespace around this
        # ought to be replaced by indent plus 4+1+len(func) spaces.
        suite = Call(func, arglist)

    suite.prefix = indent + (4 * " ")
    return Node(syms.with_stmt,
                [Name('with'),
                 with_item,
                 Name(':'),
                 Newline(),
                 suite])


def RaisesRegexOp(context, designator, exceptionClass, expected_regex,
                  indent, kws, arglist, node):
    arglist = [a.clone() for a in arglist.children]
    pattern = arglist[2]
    del arglist[2:4]  # remove pattern and comma
    arglist = Node(syms.arglist, arglist)
    with_stmt = RaisesOp(context, exceptionClass, indent, kws, arglist, node)

    # if this is already part of a with statement we need to insert re.search
    # after the last leaf with content
    if node.parent.type == syms.with_stmt:
        parent_with = node.parent
        for leaf in reversed(list(parent_with.leaves())):
            if leaf.value.strip():
                break
        i = leaf.parent.children.index(leaf)
        return with_stmt
    else:
        return Node(syms.suite, [with_stmt])


_method_map = {
    # simple ones
    'assertEqual': partial(CompOp, '=='),  # asserts.eq(A, B) || asserts.assert_that(A).is_equal_to(B)
    'assertNotEqual': partial(CompOp, '!='),
    'assertFalse': partial(UnaryOp, 'not', ''),
    'assertGreater': partial(CompOp, '>'),
    'assertGreaterEqual': partial(CompOp, '>='),
    'assertIn': partial(CompOp, 'in'),
    'assertIs': partial(CompOp, '=='),
    'assertIsNone': partial(UnaryOp, '', '== None'),
    'assertIsNot': partial(CompOp, '!='),
    'assertIsNotNone': partial(UnaryOp, '', '!= None'),
    'assertLess': partial(CompOp, '<'),
    'assertLessEqual': partial(CompOp, '<='),
    'assertNotIn': partial(CompOp, 'not in'),
    'assertTrue': partial(UnaryOp, '', ''),
    'assertIsInstance': partial(DualOp, 'isinstance(\1, \2)'),
    'assertNotIsInstance': partial(DualOp, 'not isinstance(\1, \2)'),

    # types ones
    'assertDictEqual': partial(CompOp, '=='),
    'assertListEqual': partial(CompOp, '=='),
    'assertMultiLineEqual': partial(CompOp, '=='),
    'assertSetEqual': partial(CompOp, '=='),
    'assertTupleEqual': partial(CompOp, '=='),
    'assertSequenceEqual': SequenceEqual,

    'assertDictContainsSubset': partial(DualOp, 'dict(\2, **\1) == \2'),
    'assertItemsEqual': partial(DualOp, 'sorted(\1) == sorted(\2)'),

    'assertAlmostEqual': partial(AlmostOp, "==", "<"),
    'assertNotAlmostEqual': partial(AlmostOp, "!=", ">"),

    'assertRaises': partial(RaisesOp, 'pytest.raises'),
    'assertWarns': partial(RaisesOp, 'pytest.warns'),  # new Py 3.2

    'assertRegex': partial(DualOp, 're.search(\2, \1)'),
    'assertNotRegex': partial(DualOp, 'not re.search(\2, \1)'),  # new Py 3.2

    'assertRaisesRegex': partial(RaisesRegexOp, 'pytest.raises', 'excinfo'),
    'assertWarnsRegex': partial(RaisesRegexOp, 'pytest.warns', 'record'),

    # 'assertLogs': -- not to be handled here, is an context handler only
}

for newname, oldname in (
        ('assertRaisesRegex', 'assertRaisesRegexp'),
        ('assertRegex', 'assertRegexpMatches'),
):
    if not hasattr(unittest.TestCase, newname):
        # use old name
        _method_map[oldname] = _method_map[newname]
        del _method_map[newname]

for m in list(_method_map.keys()):
    if not hasattr(unittest.TestCase, m):
        del _method_map[m]

# (Deprecated) Aliases
_method_aliases = {
    'assertEquals': 'assertEqual',
    'assertNotEquals': 'assertNotEqual',
    'assert_': 'assertTrue',
    'assertAlmostEquals': 'assertAlmostEqual',
    'assertNotAlmostEquals': 'assertNotAlmostEqual',
    'assertRegexpMatches': 'assertRegex',
    'assertRaisesRegexp': 'assertRaisesRegex',

    'failUnlessEqual': 'assertEqual',
    'failIfEqual': 'assertNotEqual',
    'failUnless': 'assertTrue',
    'failIf': 'assertFalse',
    'failUnlessRaises': 'assertRaises',
    'failUnlessAlmostEqual': 'assertAlmostEqual',
    'failIfAlmostEqual': 'assertNotAlmostEqual',
}

for a, o in list(_method_aliases.items()):
    if o not in _method_map:
        # if the original name is not a TestCase method, remove the alias
        del _method_aliases[a]

"""
Node(power,
     [Leaf(1, u'self'),
      Node(trailer,
           [Leaf(23, u'.'),
            Leaf(1, u'assertEqual')]),
      Node(trailer,
           [Leaf(7, u'('),
            Node(arglist,
                 [Leaf(1, u'abc'),
                  Leaf(12, u','),
                  Leaf(3, u"'xxx'")]),
            Leaf(8, u')')])])

Node(power,
     [Leaf(1, u'self'),
      Node(trailer,
           [Leaf(23, u'.'),
            Leaf(1, u'assertAlmostEqual')]),
      Node(trailer,
           [Leaf(7, u'('),
            Node(arglist,
                 [Leaf(2, u'100'),
                  Leaf(12, u','),
                  Leaf(1, u'klm'),
                  Leaf(12, u','),
                Node(argument,
                     [Leaf(1, u'msg'),
                      Leaf(22, u'='),
                      Leaf(3, u'"Message"')]),
                  Leaf(12, u','),
                  Node(argument,
                       [Leaf(1, u'places'),
                        Leaf(22, u'='),
                        Leaf(2, u'1')])]),
            Leaf(8, u')')])])
"""


class FixAsserts(BaseFix):
    run_order = 2

    PATTERN = """
    power< 'self'
      trailer< '.' method=( %s ) >
      trailer< '(' arglist=any ')' >
    >
    """ % ' | '.join(map(repr,
                         (set(_method_map.keys()) | set(
                             _method_aliases.keys()))))

    def transform(self, node, results):

        def process_arg(arg):
            if isinstance(arg, Leaf) and arg.type == token.COMMA:
                return
            elif (isinstance(arg, Node) and arg.type == syms.argument and
                  arg.children[1].type == token.EQUAL):
                # keyword argument
                name, equal, value = arg.children
                assert name.type == token.NAME
                assert equal.type == token.EQUAL
                value = value.clone()
                kwargs[name.value] = value
                if '\n' in arg.prefix:
                    value.prefix = arg.prefix
                else:
                    value.prefix = arg.prefix.strip() + " "
            else:
                if (isinstance(arg, Node) and arg.type == syms.argument and
                        arg.children[0].type == 36 and arg.children[
                            0].value == '**'):
                    return
                assert not kwargs, 'all positional args are assumed to come first'
                if (isinstance(arg, Node) and arg.type == syms.argument and
                        arg.children[1].type == syms.comp_for):
                    # argument is a generator expression w/o
                    # parenthesis, add parenthesis
                    value = arg.clone()
                    value.children.insert(0, Leaf(token.LPAR, '('))
                    value.children.append(Leaf(token.RPAR, ')'))
                    posargs.append(value)
                else:
                    posargs.append(arg.clone())

        method = results['method'][0].value
        # map (deprecated) aliases to original to avoid analysing
        # the decorator function
        method = _method_aliases.get(method, method)

        posargs = []
        kwargs = {}

        # This is either a "arglist" or a single argument
        if results['arglist'].type == syms.arglist:
            for arg in results['arglist'].children:
                process_arg(arg)
        else:
            process_arg(results['arglist'])

        try:
            test_func = getattr(unittest.TestCase, method)
        except AttributeError:
            raise RuntimeError("Your unittest package does not support '%s'. "
                               "consider updating the package" % method)

        required_args, argsdict = utils.resolve_func_args(test_func, posargs,
                                                          kwargs)

        if method.startswith(('assertRaises', 'assertWarns')):
            n_stmt = _method_map[method](*required_args,
                                         indent=find_indentation(node),
                                         kws=argsdict,
                                         arglist=results['arglist'],
                                         node=node)
        else:
            # n_stmt = Node(syms.assert_stmt,
            #               [Name('assert'),
            #                _method_map[method](*required_args, kws=argsdict)])
            n_stmt = Node(syms.simple_stmt,
                          [Name('asserts.'),
                           _method_map[method](*required_args, kws=argsdict)])
        if argsdict.get('msg', None) is not None:
            n_stmt.children.extend((Name(','), argsdict['msg']))

        def fix_line_wrapping(x):
            for c in x.children:
                # no need to worry about wrapping of "[", "{" and "("
                if c.type in [token.LSQB, token.LBRACE, token.LPAR]:
                    break
                if c.prefix.startswith('\n'):
                    c.prefix = c.prefix.replace('\n', ' \\\n')
                fix_line_wrapping(c)

        fix_line_wrapping(n_stmt)
        # the prefix should be set only after fixing line wrapping because it can contain a '\n'
        n_stmt.prefix = node.prefix

        # add necessary imports
        if 'Raises' in method or 'Warns' in method:
            add_import('pytest', node)
        if ('Regex' in method and not 'Raises' in method and
                not 'Warns' in method):
            add_import('re', node)
        add_import('asserts', node, ns="vendor")

        return n_stmt
