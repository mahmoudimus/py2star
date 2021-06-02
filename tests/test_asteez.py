import logging
import os.path
import unittest
from pathlib import Path
from textwrap import dedent

import astunparse
import libcst as cst
import pytest
from libcst.codemod import CodemodContext, CodemodTest
from libcst.metadata import FullyQualifiedNameProvider
from py2star.asteez import (
    functionz,
    remove_exceptions,
    remove_types,
    rewrite_class,
    rewrite_comparisons,
    rewrite_fstring,
    rewrite_imports,
    rewrite_loopz,
)

logger = logging.getLogger(__name__)


def test_remove_fstring(program):
    rewriter = rewrite_fstring.RemoveFStrings()
    rewritten = rewriter.visit(program)
    code = astunparse.unparse(rewritten)
    assert "raise ValueError(('%s, %s, %s' % (key, mode, nonce)))" in code
    assert "return ('%s' % (foo,))" in code


def test_remove_types(source_tree):
    context = CodemodContext()
    txfrmr = remove_types.RemoveTypesTransformer(context)
    rewritten = source_tree.visit(txfrmr)
    print(rewritten.code)


def test_remove_self(source_tree):
    context = CodemodContext()
    tree = source_tree
    for l in [
        rewrite_class.FunctionParameterStripper(context, ["self"]),
        rewrite_class.AttributeGetter(context, ["self"]),
    ]:
        tree = tree.visit(l)

    # print(tree.code)
    assert "self" not in tree.code


def test_convert_while_loop():
    """
    While loop converted to for loop because there's no while loops in starlark
    :return:
    """
    s = cst.parse_module(
        """
pos = 0
finish = 5
while pos <= finish:
    m = self.search(s, pos)
    if not m:
        res += s[pos:]
        break    
        
    """
    )
    expected = cst.parse_module(
        """
pos = 0
finish = 5
for _while_ in range(_WHILE_LOOP_EMULATION_ITERATION):
    if pos > finish:
        break
    m = self.search(s, pos)
    if not m:
        res += s[pos:]
        break 
            
    """
    )
    ctx = CodemodContext()
    w2f = rewrite_loopz.WhileToForLoop(ctx)
    rewritten = s.visit(w2f)
    assert expected.code.strip() == rewritten.code.strip()


class TestGeneratorAndYieldTransformations(CodemodTest):
    TRANSFORM = functionz.GeneratorToFunction

    def test_yield_to_return(self):
        before = """
        def iter():
            for i in range(10):
                yield i
        """
        after = """
        def iter():
            for i in range(10):
                return i
        """
        self.assertCodemod(before, after)

    def test_generator_to_comprehension(self):
        before = """
        c = range(12)
        x = (i for i in c)
        """
        after = """
        c = range(12)
        x = [i for i in c]
        """
        self.assertCodemod(before, after)


def test_unchain_comparison():
    context = CodemodContext()
    tree = cst.parse_module(
        """
def compare(x, y):
    if 1 < x <= y < 10:
        return True
"""
    )
    rwcc = rewrite_comparisons.UnchainComparison(context)
    rewritten = tree.visit(rwcc)
    expected = """
def compare(x, y):
    if (1 < x) and (x <= y) and (y < 10):
        return True
"""
    assert expected.strip() == rewritten.code.strip()


def test_is_comparison_transformer():
    tree = cst.parse_module(
        """
a = False
a is False
b = True
b is not False
"""
    )
    rwcc = rewrite_comparisons.IsComparisonTransformer()
    rewritten = tree.visit(rwcc)
    expected = """
a = False
a == False
b = True
b != False
"""
    assert expected.strip() == rewritten.code.strip()


class MetadataResolvingCodemodTest(CodemodTest):
    def _get_context_override(self, before):
        mod = cst.MetadataWrapper(
            cst.parse_module(self.make_fixture_data(before))
        )
        mod.resolve_many(self.TRANSFORM.METADATA_DEPENDENCIES)
        return CodemodContext(wrapper=mod)


class TestUnpackTargetAssignments(CodemodTest):
    TRANSFORM = remove_exceptions.UnpackTargetAssignments

    def test_unpack_target_assignments(self):
        before = """
        a = b = "xyz"
        """
        after = """
        a = "xyz"
        b = a
        """
        self.assertCodemod(before, after)


class TestDesugarDecorators(CodemodTest):
    TRANSFORM = remove_exceptions.DesugarDecorators

    def test_de_decorate_function(self):
        before = """
        @decorator
        @staticmethod
        def foo(a, b):
            return True
        """
        after = """
        def foo(a, b):
            return True
        foo = decorator(foo)
        """
        self.assertCodemod(before, after)

    def test_de_decorate_function_with_arguments(self):
        before = """
        @decorator(1)
        def foo(a, b):
            return True
        """
        after = """
        def foo(a, b):
            return True
        foo = decorator(1)(foo)
        """
        self.assertCodemod(before, after)

    @unittest.skip("unsupported transform")
    def test_de_decorate_class(self):
        before = """
        @decorator
        class Foo(object):
            pass
        """
        after = """
        class Foo(object):
            pass
        Foo = decorator(Foo)
        """
        self.assertCodemod(before, after)


class TestDesugarBuiltinOperators(CodemodTest):
    TRANSFORM = remove_exceptions.DesugarBuiltinOperators

    def test_desugar_power_operator(self):
        before = """
        x = 2 ** 3
        """
        after = """
        x = pow(2, 3)
        """
        self.assertCodemod(before, after)

    def test_desugar_power_operator_in_func(self):
        before = """
        def foo(x, y):
            if x:
                return x + x ** y
            else:
                return x | y
        """
        after = """
        def foo(x, y):
            if x:
                return x + pow(x, y)
            else:
                return x | y
        """
        self.assertCodemod(before, after)


class TestDesugarSetSyntax(CodemodTest):
    TRANSFORM = remove_exceptions.DesugarSetSyntax

    def test_set_expression_desugar(self):
        before = """
        {1,2}
        """
        after = """
        Set([1,2])
        """
        self.assertCodemod(before, after)

    def test_set_assignment_desugar(self):
        before = """
        x = {1,2}
        """
        after = """
        x = Set([1,2])
        """
        self.assertCodemod(before, after)


class TestTopLevelExceptionRemoval(MetadataResolvingCodemodTest):
    TRANSFORM = remove_exceptions.CommentTopLevelTryBlocks

    def test_remove_top_level_try(self):
        before = """
        try:
            from _cexcept import *
        except ImportError:
            pass
            
        def foo(x):
            try:
                x[0] = 'a'
            except IndexError:
                pass
        """
        after = """
        # try:
        #     from _cexcept import *
        # except ImportError:
        #     pass

        def foo(x):
            try:
                x[0] = 'a'
            except IndexError:
                pass
        """
        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)

    def test_remove_from_ElementTree(self):
        with open("../ElementTree.py") as f:
            before = f.read()
        after = """
       # try:
       #     from _cexcept import *
       # except ImportError:
       #     pass

       def foo(x):
           try:
               x[0] = 'a'
           except IndexError:
               pass
       """
        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)


class TestRewriteExceptions(MetadataResolvingCodemodTest):
    TRANSFORM = remove_exceptions.RemoveExceptions

    def test_map_simple_raise_statement_to_result_error(self):
        before = """
        def foo(a, b, c):
            if not a:
                raise ValueError("a: %s is not truthy!" % (a,))
        """
        after = """
        def foo(a, b, c):
            if not a:
                return Error("ValueError: a: %s is not truthy!" % (a,))
        """
        mod = cst.MetadataWrapper(
            cst.parse_module(self.make_fixture_data(before))
        )
        mod.resolve_many(self.TRANSFORM.METADATA_DEPENDENCIES)

        self.assertCodemod(
            before, after, context_override=CodemodContext(wrapper=mod)
        )

    #
    # class Element:
    #     """An XML element.
    #
    #     This class is the reference implementation of the Element interface.
    #
    #     An element's length is its number of subelements.  That means if you
    #     want to check if an element is truly empty, you should check BOTH
    #     its length AND its text attribute.
    #
    #     The element tag, attribute names, and attribute values can be either
    #     bytes or strings.
    #
    #     *tag* is the element name.  *attrib* is an optional dictionary containing
    #     element attributes. *extra* are additional element attributes given as
    #     keyword arguments.
    #
    #     Example form:
    #         <tag attrib>text<child/>...</tag>tail
    #
    #     """
    #
    #     tag = None
    #     """The element's name."""
    #
    #     attrib = None
    #     """Dictionary of the element's attributes."""
    #
    #     text = None
    #     """
    #     Text before first subelement. This is either a string or the value None.
    #     Note that if there is no text, this attribute may be either
    #     None or the empty string, depending on the parser.
    #
    #     """
    #
    #     tail = None
    #     """
    #     Text after this element's end tag, but before the next sibling element's
    #     start tag.  This is either a string or the value None.  Note that if there
    #     was no text, this attribute may be either None or an empty string,
    #     depending on the parser.
    #
    #     """
    #
    #     def __init__(self, tag, attrib={}, **extra):
    #         if not isinstance(attrib, dict):
    #             raise TypeError(
    #                 "attrib must be dict, not %s" % (attrib.__class__.__name__,)
    #             )
    #         attrib = attrib.copy()
    #         attrib.update(extra)
    #         self.tag = tag
    #         self.attrib = attrib
    #         self._children = []

    # def _fixname(self, key):
    # # expand qname, and convert name string to ascii, if possible
    # try:
    #     name = self._names[key]
    # except KeyError:
    #     name = key
    #     if "}" in name:
    #         name = "{" + name
    #     self._names[key] = name
    # return name

    #     rval = safe(self.parser.Parse)("", 1) # end of data
    # if rval.is_err:
    #     # self._raiseerror(v)
    #     return rval

    #     try:
    #     return _IterParseIterator(source, events, parser, close_source)
    # except:
    #     if close_source:
    #         source.close()
    #     raise
    def test_map_raise_statement_with_func(self):
        before = """
        class Foo(object):
        
            def _raiseerror(self, value):
                err = ParseError(value)
                err.code = value.code
                err.position = value.lineno, value.offset
                raise err
            
            def close(self):
                try:
                    self.parser.Parse("", 1) # end of data
                except self._error as v:
                    self._raiseerror(v)
        """
        after = """
        class Foo(object):
        
            def _raiseerror(self, value):
                err = ParseError(value)
                err.code = value.code
                err.position = value.lineno, value.offset
                # PY2LARKY: pay attention to this!
                return err
            
            def close(self):
                try:
                    self.parser.Parse("", 1) # end of data
                except self._error as v:
                    self._raiseerror(v)
        """
        mod = cst.MetadataWrapper(
            cst.parse_module(self.make_fixture_data(before))
        )
        mod.resolve_many(self.TRANSFORM.METADATA_DEPENDENCIES)

        self.assertCodemod(
            before, after, context_override=CodemodContext(wrapper=mod)
        )

    @unittest.skip(
        "currently unsupported. see https://github.com/MaT1g3R/option/issues/7"
    )
    def test_remove_exceptions(self):
        """
        try:
            x(y(f(xx)))
        except Exception:
            xx

        _tmp = safe(f)(xx).map(y).map(x)
        :return:
        """
        # https://github.com/MaT1g3R/option/issues/7
        before = """
        def foo(a, b, c):
            try:
                a(b, c)
            except ZeroDivisionError:
                raise ValueError("cannot divide by zero")
            except Exception:
                raise TypeError("What?")
        """
        after = """
        def foo(a, b, c):
            _tmp = safe(a)(b, c)
            if _tmp.is_ok:
                return _tmp.unwrap()
            if _tmp.
        try_(foo, 
             except_=[
               Error('ZeroDivisionError: ValueError: cannot divide by zero'),
               Error('Exception: TypeError: What?')
            ],
            finally_=[
            ])
          .except_(ZeroDivisionError, ValueError("cannot divide by zero"))
          .except_(Exception, TypeError("What?"))
        
        safe(foo)
          .
        """
        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)


def test_rewrite_typechecks():
    tree = cst.parse_module(
        """
def foo(a, b, c):
    if isinstance({}, dict):
        return "hello"
    elif callable(lambda : 1):
        return "what?"
"""
    )
    context = CodemodContext()
    c2frw = functionz.RewriteTypeChecks(context)
    rewritten = tree.visit(c2frw)
    # rewritten = c2frw.transform_module(tree)
    expected = """
def foo(a, b, c):
    if types.is_instance({}, dict):
        return "hello"
    elif types.is_callable(lambda : 1):
        return "what?"
"""
    # using split() avoids having to trim trailing whitespace.
    assert _remove_empty_lines(rewritten.code) == _remove_empty_lines(expected)


def test_class_to_function():
    tree = cst.parse_module(
        """
class Foo(object):
    def __init__(self):
        pass

class Bar(object):
    def __init__(self, var, value):
        pass

class Complicated():
    def __init__(self, x, y, z=1):
        pass

    def foo(self, one, two=2):
        pass

    @staticmethod
    def doit(a, b):
        pass
"""
    )
    context = CodemodContext()
    c2frw = rewrite_class.ClassToFunctionRewriter(
        context, remove_decorators=True
    )
    rewritten = tree.visit(c2frw)
    expected = """
def Foo():
    self = larky.mutablestruct(__class__='Foo')
    def __init__():
        pass
        return self
    self = __init__()

    return self

def Bar(var, value):
    self = larky.mutablestruct(__class__='Bar')
    def __init__(var, value):
        pass
        return self
    self = __init__(var, value)

    return self

def Complicated(x, y, z=1):
    self = larky.mutablestruct(__class__='Complicated')
    def __init__(x, y, z):
        pass
        return self
    self = __init__(x, y, z)

    def foo(one, two=2):
        pass
    self.foo = foo
    
    def doit(a, b):
        pass
    self.doit = doit

    return self
"""
    # using split() avoids having to trim trailing whitespace.
    assert _remove_empty_lines(rewritten.code) == _remove_empty_lines(expected)


def _remove_empty_lines(mystr):
    # "".join([s for s in t.strip().splitlines(True)
    #         if s.strip("\r\n").strip()])
    return [line for line in mystr.split("\n") if line.strip() != ""]


def test_rewrite_imports():
    sample = """
    from __future__ import print_function
    
    import unittest
    from binascii import unhexlify
    
    import Crypto.Hash.SHA256
    # TODO: fix this one! ==> from Crypto.PublicKey import RSA => load("@vendor//Crypto/PublicKey/RSA", "RSA")
    from Crypto.SelfTest.st_common import list_test_cases
    from Crypto.SelfTest.loader import load_test_vectors, load_test_vectors_wycheproof
    
    from Crypto.Util.py3compat import tobytes, bchr
    from Crypto.Cipher import AES
    from Crypto.Hash import SHAKE128, SHA256
    
    from Crypto.Util.strxor import strxor
    # load("@stdlib//unittest")
    """
    tree = cst.parse_module(dedent(sample))
    pkg_root = os.path.basename(__file__)
    wrapper = cst.MetadataWrapper(
        tree,
        cache={
            FullyQualifiedNameProvider: FullyQualifiedNameProvider.gen_cache(
                Path(""), [pkg_root], None
            ).get(pkg_root, "")
        },
    )
    wrapper.resolve_many(rewrite_imports.RewriteImports.METADATA_DEPENDENCIES)
    rwi = rewrite_imports.RewriteImports(
        context=CodemodContext(wrapper=wrapper, filename=pkg_root)
    )
    rewritten = wrapper.visit(rwi)
    expected = """
    load("@stdlib//unittest", unittest="unittest")
    load("@stdlib//binascii", unhexlify="unhexlify")
    
    load("@vendor//Crypto/Hash", SHA256="SHA256")
    # TODO: fix this one! ==> from Crypto.PublicKey import RSA => load("@vendor//Crypto/PublicKey/RSA", "RSA")
    load("@vendor//Crypto/SelfTest/st_common", list_test_cases="list_test_cases")
    load("@vendor//Crypto/SelfTest/loader", load_test_vectors="load_test_vectors", load_test_vectors_wycheproof="load_test_vectors_wycheproof")
    
    load("@vendor//Crypto/Util/py3compat", tobytes="tobytes", bchr="bchr")
    load("@vendor//Crypto/Cipher", AES="AES")
    load("@vendor//Crypto/Hash", SHAKE128="SHAKE128", SHA256="SHA256")
    
    load("@vendor//Crypto/Util/strxor", strxor="strxor")
    # load("@stdlib//unittest")    
"""
    # print(rewritten.code.strip())
    assert dedent(expected).strip() == dedent(rewritten.code).strip()
