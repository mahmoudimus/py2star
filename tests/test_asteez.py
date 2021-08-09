import io
import logging
import unittest

import astunparse
import libcst as cst
import pytest
from libcst.codemod import CodemodContext, CodemodTest
from py2star.asteez import (
    functionz,
    remove_exceptions,
    remove_types,
    rewrite_class,
    rewrite_comparisons,
    rewrite_fstring,
    rewrite_imports,
    rewrite_loopz,
    rewrite_tests,
)

logger = logging.getLogger(__name__)


class MetadataResolvingCodemodTest(CodemodTest):
    def _get_context_override(self, before):
        mod = cst.MetadataWrapper(
            cst.parse_module(self.make_fixture_data(before))
        )
        mod.resolve_many(self.TRANSFORM.METADATA_DEPENDENCIES)
        return CodemodContext(wrapper=mod)


# Fix for https://github.com/simonpercivall/astunparse/issues/43
class FixedAstunparseUnparser(astunparse.Unparser):
    def _Constant(self, t):
        if not hasattr(t, "kind"):
            setattr(t, "kind", None)
        super()._Constant(t)


def test_remove_fstring(program):
    rewriter = rewrite_fstring.RemoveFStrings()
    rewritten = rewriter.visit(program)
    code = io.StringIO()
    FixedAstunparseUnparser(rewritten, file=code)
    code = code.getvalue()
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
        rewrite_class.ClassInstanceVariableRemover(context, ["self"]),
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
for _while_ in range(WHILE_LOOP_EMULATION_ITERATION):
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

    def test_unpack_nested_target(self):
        before = """
        class Kite(object):
            def x(self, y):
                self.z = self.w = p = y
        """
        after = """
        class Kite(object):
            def x(self, y):
                self.z = y
                self.w = self.z
                p = self.z
        """
        self.assertCodemod(before, after)

    def test_unpack_expression(self):
        before = r"""
        class _S2V(object):
            def __init__(self, key, ciphermod, cipher_params=None):
                self._key = _copy_bytes(None, None, key)
                self._ciphermod = ciphermod
                self._last_string = self._cache = b'\x00' * ciphermod.block_size
        """

        after = r"""
        class _S2V(object):
            def __init__(self, key, ciphermod, cipher_params=None):
                self._key = _copy_bytes(None, None, key)
                self._ciphermod = ciphermod
                self._last_string = b'\x00' * ciphermod.block_size
                self._cache = self._last_string
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


class TestSubMethodsWithLibraryCallsInstead(MetadataResolvingCodemodTest):
    TRANSFORM = remove_exceptions.SubMethodsWithLibraryCallsInstead

    def test_convert_dotencode_to_codecsdotencode(self):
        before = """
        pem_key_chunks = [('-----BEGIN %s-----' % marker).encode('utf-8')]
        """

        after = """
        pem_key_chunks = [codecs.encode(('-----BEGIN %s-----' % marker), encoding='utf-8')]
        """

        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)

    def test_convert_dotdecode_to_codecsdotdecode(self):
        before = """
        long_to_base64(self.prepared_key.n).decode('ASCII'),
        """

        after = """
        codecs.decode(long_to_base64(self.prepared_key.n), encoding='ASCII'),
        """

        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)

    def test_convert_hex_to_hexlify(self):
        before = """
        b"foo".hex()
        """

        after = """
        codecs.decode(binascii.hexlify(b"foo"), encoding='utf-8')
        """

        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)


class TestRewriteImplicitStringConcat(MetadataResolvingCodemodTest):
    TRANSFORM = remove_exceptions.RewriteImplicitStringConcat

    def test_convert_implicit_string_concat(self):
        before = """
        print("Attempting to verify a message with a private key. "
              "This is not recommended.")
        """

        after = """
        print(("Attempting to verify a message with a private key. " +
              "This is not recommended."))
        """
        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)

    def test_convert_implicit_raw_string_concat(self):
        before = """
        regex1 = (
            r"pack_into requires a buffer of at least 6 "
            r"bytes for packing 1 bytes at offset 5 "
            r"\(actual buffer size is 1\)"
        )
        
        regex2 = (
            r"unpack_from requires a buffer of at least 6 "
            r"bytes for unpacking 1 bytes at offset 5 "
            r"\(actual buffer size is 1\)"
        )
        """
        after = """
        regex1 = (r"pack_into requires a buffer of at least 6 " +
            r"bytes for packing 1 bytes at offset 5 " +
            r"\(actual buffer size is 1\)")
        
        regex2 = (r"unpack_from requires a buffer of at least 6 " +
            r"bytes for unpacking 1 bytes at offset 5 " +
            r"\(actual buffer size is 1\)")
        """
        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)


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
                return Error("ValueError: " + "a: %s is not truthy!" % (a,))
        """
        mod = cst.MetadataWrapper(
            cst.parse_module(self.make_fixture_data(before))
        )
        mod.resolve_many(self.TRANSFORM.METADATA_DEPENDENCIES)

        self.assertCodemod(
            before, after, context_override=CodemodContext(wrapper=mod)
        )

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

    def test_raise_concatenatedstring(self):
        before = """
        # Section 5.3 of NIST SP 800 38B and Appendix B
        if bs == 8:
            const_Rb = 0x1B
            self._max_size = 8 * (2 ** 21)
        elif bs == 16:
            const_Rb = 0x87
            self._max_size = 16 * (2 ** 48)
        else:
            raise TypeError("CMAC requires a cipher with a block size"
                            " of 8 or 16 bytes, not %d" % bs)
        """
        after = """
        # Section 5.3 of NIST SP 800 38B and Appendix B
        if bs == 8:
            const_Rb = 0x1B
            self._max_size = 8 * (2 ** 21)
        elif bs == 16:
            const_Rb = 0x87
            self._max_size = 16 * (2 ** 48)
        else:
            return Error("TypeError: " + "CMAC requires a cipher with a block size"
                            " of 8 or 16 bytes, not %d" % bs)
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


class TestClassRewriting(MetadataResolvingCodemodTest):
    TRANSFORM = rewrite_class.ClassToFunctionRewriter

    def test_delete_kwarg_in_constructors(self):
        before = """
        class Element:
            def __init__(self, tag, attrib={}, **extra):
                if not isinstance(attrib, dict):
                    raise TypeError(
                        "attrib must be dict, not %s" % (attrib.__class__.__name__,)
                    )
                attrib = attrib.copy()
                attrib.update(extra)
                self.tag = tag
                self.attrib = attrib
                self._children = []
        """
        after = """
        def Element(tag, attrib={}, **extra):
            self = larky.mutablestruct(__name__='Element', __class__=Element)
            def __init__(tag, attrib, extra):
                if not isinstance(attrib, dict):
                    raise TypeError(
                        "attrib must be dict, not %s" % (attrib.__class__.__name__,)
                    )
                attrib = attrib.copy()
                attrib.update(extra)
                self.tag = tag
                self.attrib = attrib
                self._children = []
                return self
            self = __init__(tag, attrib, extra)
            return self
        """
        self.assertCodemod(before, after)

    @unittest.skip("THIS TEST WORKS BUT RUNNING THIS FAILS ON REAL CODE")
    def test_delete_stararg_in_constructors(self):
        before = """
        class XMLPullParser:
            def __init__(self, events=None, *, _parser=None):
                self._events_queue = []
                self._index = 0
                self._parser = _parser or XMLParser(target=TreeBuilder())
                # wire up the parser for event reporting
                if events is None:
                    events = ("end",)
                self._parser._setevents(self._events_queue, events)
        """
        after = """
        def XMLPullParser(events=None, _parser=None):
            self = larky.mutablestruct(__name__='XMLPullParser', __class__=XMLPullParser)
            def __init__(events, _parser):
                self._events_queue = []
                self._index = 0
                self._parser = _parser or XMLParser(target=TreeBuilder())
                # wire up the parser for event reporting
                if events is None:
                    events = ("end",)
                self._parser._setevents(self._events_queue, events)
                return self
            self = __init__(events, _parser)
            return self
        """
        self.assertCodemod(before, after)

    def test_class_to_function(self):
        before = """
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
        after = """
        def Foo():
            self = larky.mutablestruct(__name__='Foo', __class__=Foo)
            def __init__():
                pass
                return self
            self = __init__()
            return self
        def Bar(var, value):
            self = larky.mutablestruct(__name__='Bar', __class__=Bar)
            def __init__(var, value):
                pass
                return self
            self = __init__(var, value)
            return self
        def Complicated(x, y, z=1):
            self = larky.mutablestruct(__name__='Complicated', __class__=Complicated)
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
        self.assertCodemod(before, after, remove_decorators=True)


def _remove_empty_lines(mystr):
    # "".join([s for s in t.strip().splitlines(True)
    #         if s.strip("\r\n").strip()])
    return [line for line in mystr.split("\n") if line.strip() != ""]


class TestAssertStatementRewriter(MetadataResolvingCodemodTest):

    TRANSFORM = remove_exceptions.AssertStatementRewriter

    def test_simple_assert_rewrite(self):
        before = """
        assert 1 == 1, "what?"
        """

        after = """
        if not (1 == 1):
            fail("what?")
        """
        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)

    def test_assert_with_default_msg(self):
        before = """
        assert 1 == 1
        """

        after = """
        if not (1 == 1):
            fail("assert 1 == 1 failed!")
        """
        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)

    def test_nested_assert(self):
        before = """
        def foo():
            assert True != False
            return True
        """

        after = """
        def foo():
            if not (True != False):
                fail("assert True != False failed!")
            return True
        """
        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)


class TestSwapByteLiteralPrefix(MetadataResolvingCodemodTest):

    TRANSFORM = remove_exceptions.SwapByteStringPrefixes

    def test_simple(self):
        before = """
        p = re.compile(br'\$2a\$([0-9][0-9])\$([A-Za-z0-9./]{22,22})([A-Za-z0-9./]{31,31})')
        """

        after = """
        p = re.compile(rb'\$2a\$([0-9][0-9])\$([A-Za-z0-9./]{22,22})([A-Za-z0-9./]{31,31})')
        """
        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)

    def test_only_swaps_the_prefix(self):
        before = """
        x = br"brrbrbbr"
        """

        after = """
        x = rb"brrbrbbr"
        """
        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)


class TestRewriteImporting(MetadataResolvingCodemodTest):

    TRANSFORM = rewrite_imports.RewriteImports

    # def test_relative_import_from_ElementTree(self):
    #     with open("../ElementTree.py") as f:
    #         before = f.read()
    #     after = """
    #    # try:
    #    #     from _cexcept import *
    #    # except ImportError:
    #    #     pass
    #
    #    def foo(x):
    #        try:
    #            x[0] = 'a'
    #        except IndexError:
    #            pass
    #    """
    #     ctx = self._get_context_override(before)
    #     ctx = dataclasses.replace(ctx,
    #                               full_module_name="xml.etree.ElementTree")
    #     self.assertCodemod(before, after, context_override=ctx)

    def test_rewrite_imports(self):
        before = """
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
        # pkg_root = os.path.basename(__file__)
        # wrapper = cst.MetadataWrapper(
        #  tree,
        #  cache={
        #    FullyQualifiedNameProvider: FullyQualifiedNameProvider.gen_cache(
        #      Path(""), [pkg_root], None
        #    ).get(pkg_root, "")
        #  },
        # )
        # wrapper.resolve_many(rewrite_imports.RewriteImports.METADATA_DEPENDENCIES)
        # rwi = rewrite_imports.RewriteImports(
        #     context=CodemodContext(wrapper=wrapper, filename=pkg_root)
        # )
        # rewritten = wrapper.visit(rwi)
        after = """
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
        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)
        # print(rewritten.code.strip())
        # assert dedent(expected).strip() == dedent(rewritten.code).strip()


class TestImportSorting(MetadataResolvingCodemodTest):

    TRANSFORM = rewrite_imports.LarkyImportSorter

    def test_import_sorters(self):
        before = """
        '''Lightweight XML support for Python.
        
         XML is an inherently hierarchical data format, and the most natural way to
         represent it is with a tree.  This module has two classes for this purpose:
        
            1. ElementTree represents the whole XML document as a tree and
        
            2. Element represents a single node in this tree.
        
         Interactions with the whole document (reading and writing to/from files) are
         usually done on the ElementTree level.  Interactions with a single XML element
         and its sub-elements are done on the Element level.
        
         Element is a flexible container object designed to store hierarchical data
         structures in memory. It can be described as a cross between a list and a
         dictionary.  Each Element has a number of properties associated with it:
        
            'tag' - a string containing the element's name.
        
            'attributes' - a Python dictionary storing the element's attributes.
        
            'text' - a string containing the element's text content.
        
            'tail' - an optional string containing text after the element's end tag.
        
            And a number of child elements stored in a Python sequence.
        
         To create an element instance, use the Element constructor,
         or the SubElement factory function.
        
         You can also use the ElementTree class to wrap an element structure
         and convert it to and from XML.
         
         '''
        
        # ---------------------------------------------------------------------
        # Licensed to PSF under a Contributor Agreement.
        # See http://www.python.org/psf/license for licensing details.
        #
        # ElementTree
        # Copyright (c) 1999-2008 by Fredrik Lundh.  All rights reserved.
        #
        # fredrik@pythonware.com
        # http://www.pythonware.com
        # --------------------------------------------------------------------
        # The ElementTree toolkit is
        #
        # Copyright (c) 1999-2008 by Fredrik Lundh
        #
        # By obtaining, using, and/or copying this software and/or its
        # associated documentation, you agree that you have read, understood,
        # and will comply with the following terms and conditions:
        #
        # Permission to use, copy, modify, and distribute this software and
        # its associated documentation for any purpose and without fee is
        # hereby granted, provided that the above copyright notice appears in
        # all copies, and that both that copyright notice and this permission
        # notice appear in supporting documentation, and that the name of
        # Secret Labs AB or the author not be used in advertising or publicity
        # pertaining to distribution of the software without specific, written
        # prior permission.
        #
        # SECRET LABS AB AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD
        # TO THIS SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANT-
        # ABILITY AND FITNESS.  IN NO EVENT SHALL SECRET LABS AB OR THE AUTHOR
        # BE LIABLE FOR ANY SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY
        # DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
        # WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS
        # ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE
        # OF THIS SOFTWARE.
        # --------------------------------------------------------------------
        
        __all__ = [
            # public symbols
            "Comment",
            "dump",
            "Element",
            "ElementTree",
            "fromstring",
            "fromstringlist",
            "iselement",
            "iterparse",
            "parse",
            "ParseError",
            "PI",
            "ProcessingInstruction",
            "QName",
            "SubElement",
            "tostring",
            "tostringlist",
            "TreeBuilder",
            "VERSION",
            "XML",
            "XMLID",
            "XMLParser",
            "register_namespace",
        ]
        
        VERSION = "1.3.0"
        
        load("@stdlib//sys", sys="sys")
        load("@stdlib//re", re="re")
        load("@stdlib//warnings", warnings="warnings")
        load("@stdlib//io", io="io")
        load("@stdlib//contextlib", contextlib="contextlib")
        
        load("@stdlib//xml/etree", ElementPath="ElementPath")
        load("@vendor//option/result", Error="Error")
        load("@stdlib//types", types="types")
        """

        after = """
        '''Lightweight XML support for Python.
        
         XML is an inherently hierarchical data format, and the most natural way to
         represent it is with a tree.  This module has two classes for this purpose:
        
            1. ElementTree represents the whole XML document as a tree and
        
            2. Element represents a single node in this tree.
        
         Interactions with the whole document (reading and writing to/from files) are
         usually done on the ElementTree level.  Interactions with a single XML element
         and its sub-elements are done on the Element level.
        
         Element is a flexible container object designed to store hierarchical data
         structures in memory. It can be described as a cross between a list and a
         dictionary.  Each Element has a number of properties associated with it:
        
            'tag' - a string containing the element's name.
        
            'attributes' - a Python dictionary storing the element's attributes.
        
            'text' - a string containing the element's text content.
        
            'tail' - an optional string containing text after the element's end tag.
        
            And a number of child elements stored in a Python sequence.
        
         To create an element instance, use the Element constructor,
         or the SubElement factory function.
        
         You can also use the ElementTree class to wrap an element structure
         and convert it to and from XML.

         '''
        
        # ---------------------------------------------------------------------
        # Licensed to PSF under a Contributor Agreement.
        # See http://www.python.org/psf/license for licensing details.
        #
        # ElementTree
        # Copyright (c) 1999-2008 by Fredrik Lundh.  All rights reserved.
        #
        # fredrik@pythonware.com
        # http://www.pythonware.com
        # --------------------------------------------------------------------
        # The ElementTree toolkit is
        #
        # Copyright (c) 1999-2008 by Fredrik Lundh
        #
        # By obtaining, using, and/or copying this software and/or its
        # associated documentation, you agree that you have read, understood,
        # and will comply with the following terms and conditions:
        #
        # Permission to use, copy, modify, and distribute this software and
        # its associated documentation for any purpose and without fee is
        # hereby granted, provided that the above copyright notice appears in
        # all copies, and that both that copyright notice and this permission
        # notice appear in supporting documentation, and that the name of
        # Secret Labs AB or the author not be used in advertising or publicity
        # pertaining to distribution of the software without specific, written
        # prior permission.
        #
        # SECRET LABS AB AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD
        # TO THIS SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANT-
        # ABILITY AND FITNESS.  IN NO EVENT SHALL SECRET LABS AB OR THE AUTHOR
        # BE LIABLE FOR ANY SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY
        # DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
        # WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS
        # ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE
        # OF THIS SOFTWARE.
        # --------------------------------------------------------------------
        
        load("@stdlib//contextlib", contextlib="contextlib")
        load("@stdlib//io", io="io")
        load("@stdlib//re", re="re")
        load("@stdlib//sys", sys="sys")
        load("@stdlib//types", types="types")
        load("@stdlib//warnings", warnings="warnings")
        load("@stdlib//xml/etree", ElementPath="ElementPath")
        load("@vendor//option/result", Error="Error")
        
        __all__ = [
            # public symbols
            "Comment",
            "dump",
            "Element",
            "ElementTree",
            "fromstring",
            "fromstringlist",
            "iselement",
            "iterparse",
            "parse",
            "ParseError",
            "PI",
            "ProcessingInstruction",
            "QName",
            "SubElement",
            "tostring",
            "tostringlist",
            "TreeBuilder",
            "VERSION",
            "XML",
            "XMLID",
            "XMLParser",
            "register_namespace",
        ]
        
        VERSION = "1.3.0"
        """
        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)


class TestDelKeyword(MetadataResolvingCodemodTest):

    TRANSFORM = rewrite_imports.RemoveDelKeyword

    def test_remove_del_keyword(self):
        before = """
        class Foo:
            def close(self):
                '''Finish feeding data to parser and return element structure.
                '''
                try:
                    self.parser.Parse("", 1)  # end of data
                except self._error as v:
                    self._raiseerror(v)
                try:
                    close_handler = self.target.close
                except AttributeError:
                    pass
                else:
                    return close_handler()
                finally:
                    # get rid of circular references
                    del self.parser, self._parser
                    del self.target, self._target
            def __delitem__(self, index):
                del self._children[index]                    

        def register_namespace(prefix, uri):
            '''Register a namespace prefix.
        
            The registry is global, and any existing mapping for either the
            given prefix or the namespace URI will be removed.
        
            *prefix* is the namespace prefix, *uri* is a namespace uri. Tags and
            attributes in this namespace will be serialized with prefix if possible.
        
            ValueError is raised if prefix is reserved or is invalid.
        
            '''
            if re.match("ns\d+$", prefix):
                raise ValueError("Prefix format reserved for internal use")
            for k, v in list(_namespace_map.items()):
                if k == uri or v == prefix:
                    del _namespace_map[k]
            _namespace_map[uri] = prefix
        """

        after = """
        class Foo:
            def close(self):
                '''Finish feeding data to parser and return element structure.
                '''
                try:
                    self.parser.Parse("", 1)  # end of data
                except self._error as v:
                    self._raiseerror(v)
                try:
                    close_handler = self.target.close
                except AttributeError:
                    pass
                else:
                    return close_handler()
                finally:
                    # get rid of circular references
                    # del self.parser, self._parser
                    pass
                    # del self.target, self._target
                    pass
            def __delitem__(self, index):
                operator.delitem(self._children, index)

        def register_namespace(prefix, uri):
            '''Register a namespace prefix.
        
            The registry is global, and any existing mapping for either the
            given prefix or the namespace URI will be removed.
        
            *prefix* is the namespace prefix, *uri* is a namespace uri. Tags and
            attributes in this namespace will be serialized with prefix if possible.
        
            ValueError is raised if prefix is reserved or is invalid.
        
            '''
            if re.match("ns\d+$", prefix):
                raise ValueError("Prefix format reserved for internal use")
            for k, v in list(_namespace_map.items()):
                if k == uri or v == prefix:
                    operator.delitem(_namespace_map, k)
            _namespace_map[uri] = prefix
        """
        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)


class TestUnittest2Functions(MetadataResolvingCodemodTest):

    TRANSFORM = rewrite_tests.Unittest2Functions

    def test_rewrite_simple_class(self):
        before = """
        class B(unittest.TestCase):
            foo = 'manchu'
            bar = []
        
            def test_do_baz(self):
                self.assertEqual(1, 1)
        
            def test_do_it_again(self):
                # do something
                bar2 = [int(x) for x in self.bar]
                self.assertEqual(bar2, map(int, self.bar))
        """

        after = """
        foo = 'manchu'
        bar = []
        
        def B_test_do_baz():
            asserts.assert_that(1).is_equal_to(1)
        
        def B_test_do_it_again():
            # do something
            bar2 = [int(x) for x in bar]
            asserts.assert_that(bar2).is_equal_to(map(int, bar))"""
        # lets re-write the assert statements
        ctx = TestAssertStatementRewriter()._get_context_override(before)
        rewriter = rewrite_tests.UnittestAssertMethodsRewriter(ctx)
        before = ctx.module.visit(rewriter).code
        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)


@pytest.mark.usefixtures("simple_class_before")
class TestUnittestAssertMethodsRewriter(MetadataResolvingCodemodTest):

    TRANSFORM = rewrite_tests.UnittestAssertMethodsRewriter

    # @pytest.fixture(autouse=True)
    # def fixture(self, simple_class):
    #     self.before = simple_class
    def test_assert_statement_rewriter(self):
        before = self.before_transform

        after = r'''
        from unittest import TestCase
        import unittest
        
        
        def AES(key, mode, nonce=None):
            print(key, mode, nonce)
            raise ValueError(f"{key}, {mode}, {nonce}")
        
        
        class RewriteMe(TestCase):
            def bar(self, q, w, z):
                # this does some stuff
                return [q, w, z]
        
            def xor(self, baz):
                # multi
                # line
                # comment
                pass
        
            def write(self):
                return self.__dict__.get("foo")
        
            def do_it(self):
                x = b"foo"
                return x
        
            def do_it2(self):
                x = b"fxxx\x80"
                return x
        
            def do_it3(self):
                x = b"\x01\x00\x10\x80"
                return x
        
            def do_it4(self):
                x = b"fo0\x7F"
                return x
        
            def test_success(self):
                asserts.assert_that(1).is_not_equal_to(2)
                asserts.assert_that(None).is_none()
                asserts.assert_that([]).is_not_none()
                asserts.assert_that(True).is_true()
        
            def test_fail(self):
                asserts.assert_that(1).is_equal_to(1)
        
            def test_doit(self):
                x = "foo"
                asserts.assert_that(re.search("her.*", "herpa")).is_not_none()
                asserts.assert_that(not re.search("xxx", x)).is_false()
                asserts.assert_fails(lambda: len(foo=42, bar=43), ".*?RuntimeError.*text .* match")
        
            def test_fstring(self) -> str:
                foo = 1
                return f"{foo}"
        
            def test_raises(self):
                key_128 = 128
                MODE_GCM = "gcm"
                asserts.assert_fails(lambda: AES(key_128, MODE_GCM, nonce=b""), ".*?ValueError")
        
            def test_bool(self):
                v1, v2, v3, v4 = (0, 10, -9, 2 ** 10)
                asserts.assert_that(v1).is_false()
                asserts.assert_that(bool(v1)).is_false()
                asserts.assert_that(v2).is_true()
                asserts.assert_that(bool(v2)).is_true()
                asserts.assert_that(v3).is_true()
                asserts.assert_that(v4).is_true()
        
            def test_upper(self):
                asserts.assert_that("foo".upper()).is_equal_to("FOO")
        
            def test_isupper(self):
                asserts.assert_that("FOO".isupper()).is_true()
                asserts.assert_that("Foo".isupper()).is_false()
        
            def test_split(self):
                s = "hello world"
                asserts.assert_that(s.split()).is_equal_to(["hello", "world"])
                def _larky_747221237():
                    s.split(2)
                # check that s.split fails when the separator is not a string
                asserts.assert_fails(lambda: _larky_747221237(), ".*?TypeError")
        
                asserts.assert_fails(lambda: int("XYZ"), ".*?ValueError.*invalid literal for.*XYZ'$")
                def _larky_597382238():
                    int("XYZ")
                asserts.assert_fails(lambda: _larky_597382238(), ".*?ValueError.*literal")
        
            def test_default_widget_size(self):
                widget = "The widget"
                asserts.assert_that(len(widget)).is_equal_to((50, 50))
        
            def test_even(self):
                """
                Test that numbers between 0 and 5 are all even.
                """
                for i in range(0, 6):
                    with self.subTest(i=i):
                        self.assertEqual(i % 2, 0)
        
            def test_warn(self):
                asserts.assert_fails(lambda: len("XYZ"), ".*?DeprecationWarning.*len\(\) is deprecated")
                def _larky_1432088325():
                    len("/etc/passwd")
        
                asserts.assert_fails(lambda: _larky_1432088325(), ".*?RuntimeWarning.*unsafe frobnicating")
'''
        ctx = self._get_context_override(before)
        self.assertCodemod(before, after, context_override=ctx)
