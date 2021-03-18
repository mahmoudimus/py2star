# -*- coding: utf-8 -*-
"""Optional fixer that changes all unprefixed string literals "..." to b"...".

br'abcd' is a SyntaxError on Python 2 but valid on Python 3.
ur'abcd' is a SyntaxError on Python 3 but valid on Python 2.
"""
import re
import typing

from lib2to3.pgen2 import token
from lib2to3.fixer_util import syms
from lib2to3 import fixer_base
from lib2to3 import fixer_util
from lib2to3 import pytree

from py2star import utils


# match bR'..' or rB'...'
_literal_re = re.compile(r'([rR]?[bBuU]|[bBuU][rR]?)[\'\"]')


class FixBytestring(fixer_base.BaseFix):
    BM_compatible = True
    PATTERN = "STRING"

    def transform(self, node: pytree.Node, results: typing.Dict):
        if node.type == token.STRING:
            if _literal_re.match(node.value):
                # guaranteed to not throw exception, since we just matched
                prefix = _literal_re.findall(node.value)[0]
                _, _, new_value = node.value.rpartition(prefix)
                new = node.clone()
                new.value = 'builtins.bytes(' + new_value + ')'
                new.parent = node.parent
                fixer_util.touch_import(None, "builtins", new)
                return new
