# -*- coding: utf-8 -*-
"""
We do not support byte literals in Larky, so we need to rewrite any
literal that starts with rB'' or br'' etc with
bytes(r'...', encoding='utf-8')
"""
import re
import typing
from lib2to3 import fixer_base, pytree
from lib2to3.pgen2 import token

from py2star import utils

# match bR'..' or rB'...'
_literal_re = re.compile(r"([rR]?[bBuU]|[bBuU][rR]?)[\'\"]")


class FixBytestring(fixer_base.BaseFix):
    order = "pre"
    run_order = 1
    BM_compatible = True
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
        new.value = "builtins.bytes(r" + new_value + ", encoding='utf-8')"
        new.parent = node.parent
        utils.add_larky_import(None, "builtins", new)
        return new
