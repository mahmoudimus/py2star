"""
Translates

    def foo(a, b, c):
        if a:
            raise ValueError("you suck!")
        return b if c else False

to:

    def foo(a, b, c):
        if a:
            fail(" ValueError(\"you suck!\")")
        return b if c else False
"""
from lib2to3 import fixer_base
from lib2to3.fixer_util import Call, Comma, Name, Node, String
from lib2to3.pgen2 import token


class FixExceptions(fixer_base.BaseFix):
    order = "pre"
    run_order = 1  # Fixers will be sorted by run order before execution
    # Lower numbers will be run first.

    BM_compatible = True
    PATTERN = """
    raise_stmt< 'raise' exc=any [',' val=any [',' tb=any]] >
    """

    def transform(self, node, results):
        syms = self.syms

        exc = results["exc"].clone()
        if exc.type == token.STRING:
            msg = "Python 3 does not support string exceptions"
            self.cannot_convert(node, msg)
            return

        if "tb" in results:
            tb = results["tb"].clone()
        else:
            tb = None
        if "val" in results:
            val = results["val"].clone()
            args = [exc, Comma(), val]
            if tb is not None:
                args += [Comma(), tb]
            return Node(syms.simple_stmt, [Call(Name("fail"), args)])

        if tb is not None:
            # tb.prefix = ""
            # exc_list = Attr(exc, Name("with_traceback")) + [ArgList([tb])]
            msg = "We do not support with_traceback in Larky"
            self.cannot_convert(node, msg)
            return

        normalized = (
            str(exc)
            .encode("unicode-escape")
            .replace(b'"', b'\\"')
            .decode("utf-8")
        )

        exc_list = [String('"'), String(normalized), String('"')]

        return Node(
            syms.simple_stmt, [Call(Name("fail"), exc_list)], prefix=node.prefix
        )
