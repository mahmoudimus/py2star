# -*- coding: utf-8 -*-
import inspect
import tokenize
from lib2to3.pgen2 import token

try:
    from inspect import Parameter
except ImportError:
    # Python 2
    pass
from lib2to3.fixer_util import syms
from lib2to3 import fixer_util
import re


class SelfMarker:
    pass


def get_parent_of_type(node, node_type):
    while node:
        if node.type == node_type:
            return node
        node = node.parent


def get_import_nodes(node):
    return [
        x
        for c in node.children
        for x in c.children
        if c.type == syms.simple_stmt and fixer_util.is_import(x)
    ]


def is_import(module_name):
    if fixer_util.is_import(module_name):
        return True
    # if its not,
    import_name = str(module_name)
    load_stmt = re.compile(r"load\((?:.+)?(@\w+)//(\w+)[,)]?")
    mo = load_stmt.match(import_name)
    if mo:
        return True
    return False


def _is_import_stmt(node):
    return (
        node.type == syms.simple_stmt
        and node.children
        and is_import(node.children[0])
    )


def add_larky_import(package, name, node):
    """Works like `does_tree_import` but adds an import statement
    if it was not imported."""

    root = fixer_util.find_root(node)

    if fixer_util.does_tree_import(package, name, root):
        return

    _seen_imports = set()
    # figure out where to insert the new import.  First try to find
    # the first import and then skip to the last one.
    insert_pos = offset = 0
    for idx, node in enumerate(root.children):
        if not _is_import_stmt(node):
            continue
        _seen_imports.add(str(node))
        for offset, node2 in enumerate(root.children[idx:]):
            if not _is_import_stmt(node2):
                break
            _seen_imports.add(str(node2))
        insert_pos = idx + offset
        break

    # if there are no imports where we can insert, find the docstring.
    # if that also fails, we stick to the beginning of the file
    if insert_pos == 0:
        for idx, node in enumerate(root.children):
            if (
                node.type == syms.simple_stmt
                and node.children
                and node.children[0].type == token.STRING
            ):
                insert_pos = idx + 1
                break

    ns = package
    if package is None:
        ns = "stdlib"

    import_ = fixer_util.Call(
        fixer_util.Name("load"),
        args=[
            fixer_util.String(f'"@{ns}//{name}"'),
            fixer_util.Comma(),
            fixer_util.String(f'"{name}"'),
        ],
    )

    children = [import_, fixer_util.Newline()]
    final_node = fixer_util.Node(syms.simple_stmt, children)

    # if we've already imported this thing, skip
    if str(final_node) in _seen_imports:
        return

    root.insert_child(insert_pos, final_node)


def resolve_func_args(test_func, posargs, kwargs):
    sig = inspect.signature(test_func)
    assert list(iter(sig.parameters))[0] == "self"
    posargs.insert(0, SelfMarker)
    ba = sig.bind(*posargs, **kwargs)
    ba.apply_defaults()
    args = ba.arguments
    required_args = [
        n
        for n, v in sig.parameters.items()
        if (
            v.default is Parameter.empty
            and v.kind not in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD)
        )
    ]
    assert args["self"] == SelfMarker
    assert required_args[0] == "self"
    del required_args[0], args["self"]
    required_args = [args[n] for n in required_args]

    return required_args, args


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


# From: https://github.com/python/cpython/blob/3.9/Tools/scripts/reindent.py
class ReIndenter:
    def __init__(self, f):
        self.after = []
        self.find_stmt = 1  # next token begins a fresh stmt?
        self.level = 0  # current indent level

        # Raw file lines.
        self.raw = f.readlines()

        # File lines, rstripped & tab-expanded.  Dummy at start is so
        # that we can use tokenize's 1-based line numbering easily.
        # Note that a line is all-blank iff it's "\n".
        self.lines = [_rstrip(line).expandtabs() + "\n" for line in self.raw]
        self.lines.insert(0, None)
        self.index = 1  # index into self.lines of next line

        # List of (lineno, indentlevel) pairs, one for each stmt and
        # comment line.  indentlevel is -1 for comment lines, as a
        # signal that tokenize doesn't know what to do about them;
        # indeed, they're our headache!
        self.stats = []

        # Save the newlines found in the file so they can be used to
        #  create output without mutating the newlines.
        self.newlines = f.newlines

    def run(self):
        tokens = tokenize.generate_tokens(self.getline)
        for _token in tokens:
            self.tokeneater(*_token)
        # Remove trailing empty lines.
        lines = self.lines
        while lines and lines[-1] == "\n":
            lines.pop()
        # Sentinel.
        stats = self.stats
        stats.append((len(lines), 0))
        # Map count of leading spaces to # we want.
        have2want = {}
        # Program after transformation.
        # Copy over initial empty lines -- there's nothing to do until
        # we see a line with *something* on it.
        after = self.after
        i = stats[0][0]
        after.extend(lines[1:i])
        for i in range(len(stats) - 1):
            thisstmt, thislevel = stats[i]
            nextstmt = stats[i + 1][0]
            have = get_leading_spaces(lines[thisstmt])
            want = thislevel * 4
            if want < 0:
                # A comment line.
                if have:
                    # An indented comment line.  If we saw the same
                    # indentation before, reuse what it most recently
                    # mapped to.
                    want = have2want.get(have, -1)
                    if want < 0:
                        # Then it probably belongs to the next real stmt.
                        for j in range(i + 1, len(stats) - 1):
                            jline, jlevel = stats[j]
                            if jlevel >= 0:
                                if have == get_leading_spaces(lines[jline]):
                                    want = jlevel * 4
                                break
                    if want < 0:  # Maybe it's a hanging
                        # comment like this one,
                        # in which case we should shift it like its base
                        # line got shifted.
                        for j in range(i - 1, -1, -1):
                            jline, jlevel = stats[j]
                            if jlevel >= 0:
                                want = have + (
                                    get_leading_spaces(after[jline - 1])
                                    - get_leading_spaces(lines[jline])
                                )
                                break
                    if want < 0:
                        # Still no luck -- leave it alone.
                        want = have
                else:
                    want = 0
            assert want >= 0
            have2want[have] = want
            diff = want - have
            if diff == 0 or have == 0:
                after.extend(lines[thisstmt:nextstmt])
            else:
                for line in lines[thisstmt:nextstmt]:
                    if diff > 0:
                        if line == "\n":
                            after.append(line)
                        else:
                            after.append(" " * diff + line)
                    else:
                        remove = min(get_leading_spaces(line), -diff)
                        after.append(line[remove:])
        return self.raw != self.after

    def write(self, f):
        f.writelines(self.after)

    # Line-getter for tokenize.
    def getline(self):
        if self.index >= len(self.lines):
            line = ""
        else:
            line = self.lines[self.index]
            self.index += 1
        return line

    # Line-eater for tokenize.
    def tokeneater(
        self,
        type,
        token,
        slinecol,
        end,
        line,
        INDENT=tokenize.INDENT,
        DEDENT=tokenize.DEDENT,
        NEWLINE=tokenize.NEWLINE,
        COMMENT=tokenize.COMMENT,
        NL=tokenize.NL,
    ):

        if type == NEWLINE:
            # A program statement, or ENDMARKER, will eventually follow,
            # after some (possibly empty) run of tokens of the form
            #     (NL | COMMENT)* (INDENT | DEDENT+)?
            self.find_stmt = 1

        elif type == INDENT:
            self.find_stmt = 1
            self.level += 1

        elif type == DEDENT:
            self.find_stmt = 1
            self.level -= 1

        elif type == COMMENT:
            if self.find_stmt:
                self.stats.append((slinecol[0], -1))
                # but we're still looking for a new stmt, so leave
                # find_stmt alone

        elif type == NL:
            pass

        elif self.find_stmt:
            # This is the first "real token" following a NEWLINE, so it
            # must be the first token of the next program statement, or an
            # ENDMARKER.
            self.find_stmt = 0
            if line:  # not endmarker
                self.stats.append((slinecol[0], self.level))


def _rstrip(line, JUNK="\n \t"):
    """Return line stripped of trailing spaces, tabs, newlines.
    Note that line.rstrip() instead also strips sundry control characters,
    but at least one known Emacs user expects to keep junk like that, not
    mentioning Barry by name or anything <wink>.
    """

    i = len(line)
    while i > 0 and line[i - 1] in JUNK:
        i -= 1
    return line[:i]


# Count number of leading blanks.
def get_leading_spaces(line):
    i, n = 0, len(line)
    while i < n and line[i] == " ":
        i += 1
    return i
