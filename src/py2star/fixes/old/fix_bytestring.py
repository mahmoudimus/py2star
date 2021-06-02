# -*- coding: utf-8 -*-
"""
We do not support byte literals in Larky, so we need to rewrite any
literal that starts with rB'' or br'' etc with
bytes(r'...', encoding='utf-8')
"""
import re
import typing
import ast
from lib2to3 import fixer_base, pytree
from lib2to3.pgen2 import token

from py2star import utils

# match bR'..' or rB'...'
_literal_re = re.compile(r"([rR]?[bB]|[bB][rR]?)[\'\"]")


class FixBytestring(fixer_base.BaseFix):
    order = "pre"
    run_order = 1
    BM_compatible = True
    explicit = True
    PATTERN = "STRING"

    def transform(self, node: pytree.Node, results: typing.Dict):
        if node.type != token.STRING:
            return

        if not _literal_re.match(node.value):
            return

        # guaranteed to not throw exception, since we just matched
        prefix = _literal_re.findall(node.value)[0]
        _, _, new_value = node.value.rpartition(prefix)
        new = node.clone()
        actual = [
            format(x, "02x")
            for x in ast.literal_eval(node.value)
            if x not in (ord('"'), ord("'"))
        ]
        # values = []
        # current = None
        # actual = []
        # for x in new_value:
        #     i = x
        #     if not isinstance(i, int):
        #         i = ord(x)
        #     # print("---> ", x, i)
        #     if x == '"':  # skip enclosing quotes
        #         continue
        #     if isinstance(i, int) and str.isascii(chr(i)):
        #         if current is None:
        #             current = []
        #         else:
        #             values.append(current)  # set in values, then clear current
        #             current = []
        #         current.append(chr(i))
        #     else:
        #         if current is None:
        #             current = []
        #         else:
        #             values.append(
        #                 'bytes(r"' + "".join(current) + '", encoding="utf-8")'
        #             )
        #             current = []
        #         current.append(format(i, "02x"))
        #
        #     actual.append(format(i, "02x"))

        # print(values)
        # new.value = "builtins.bytes(r" + new_value + ", encoding='utf-8')"
        if len(actual) > 0:
            new.value = "bytes([" + "0x" + ", 0x".join(actual) + "])"
        else:
            new.value = "bytes(r" + new_value + ", encoding='utf-8')"
        new.parent = node.parent
        utils.add_larky_import(None, "builtins", new)
        return new
