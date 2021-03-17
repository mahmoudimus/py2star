import argparse
import logging
import sys
import textwrap
import token
from tokenize import tokenize

logger = logging.getLogger(__name__)

TOKENS_OF_INTEREST = (
    "def",
    "class",
)


def transform(string, in_def):
    return string if in_def else string.replace('class', 'def')


# https://stackoverflow.com/a/38181014/133514
def find_definitions(filename):
    with open(filename, "rb") as f:
        gen = tokenize(f.readline)
        for tok in gen:
            if tok.type != token.NAME:
                continue
            if tok.string not in TOKENS_OF_INTEREST:
                continue

            definition = _extract_definition(gen, tok)
            yield "".join(definition)


def _extract_definition(gen, tok):
    in_def = tok.string == "def"
    indent_level = 1
    # function or class definition, read until next colon outside
    # parentheses.
    definition, last_line = [transform(tok.line, in_def)], tok.end[0]
    if in_def:
        # track indentation level so we can indent the docstring
        indent_level += (tok.line.find('def') // 4)
    try:
        tok = _on_function_or_class(definition, gen, last_line, tok)
        # function stops ^
    except StopIteration:
        return definition

    try:
        d = _on_comment_or_docstring(gen, tok)
    except StopIteration:
        return definition

    definition.append(
        textwrap.indent(
            '"""\n' + ''.join(d) + '\n"""',
            ' ' * 4 * indent_level)
    )
    return definition


def _on_comment_or_docstring(gen, tok):
    # comments
    while tok.exact_type not in [token.COMMENT, token.STRING]:
        tok = next(gen)
    d = []
    while tok.exact_type in [token.COMMENT, token.STRING, token.NL]:
        d.append(
            tok.string
                .strip('"""')  # replace docstrings
                .lstrip('#')  # replace comment
                .strip('"'))
        tok = next(gen)
    return d


def _on_function_or_class(definition, gen, last_line, tok):
    parens = 0
    while tok.exact_type != token.COLON or parens > 0:

        # this logic allows us to detect whether or not we
        # are in a multi-line function signature
        if last_line != tok.end[0]:
            definition.append(tok.line)
            last_line = tok.end[0]

        # parenthesis open / close
        if tok.exact_type == token.LPAR:
            parens += 1
        elif tok.exact_type == token.RPAR:
            parens -= 1
        logger.debug(tok)
        tok = next(gen)
    if last_line != tok.end[0]:
        definition.append(tok.line)
    return tok
