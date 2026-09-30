"""
String formatting whose Larky support varies by host: f-strings, format
specs or conversions in str.format() fields, and printf-style ``%``
formatting. All three become string concatenation of the literal text and
``format(value, spec)`` / ``str()`` / ``repr()`` calls, so the output needs
only a ``format()`` built-in that follows Python's format spec
mini-language, which a host can provide; Starlark's own ``%`` supports only
bare conversions and cannot always be changed.
"""
import re
import string
from _string import formatter_field_name_split
from typing import List, Optional, Union

import libcst as cst
import libcst.matchers as m
from libcst import codemod

Piece = Union[str, cst.BaseExpression]


def _str(value: str) -> cst.SimpleString:
    """A double-quoted string literal for value."""
    r = repr(value)
    if r[0] == "'":
        r = '"' + r[1:-1].replace("\\'", "'").replace('"', '\\"') + '"'
    return cst.SimpleString(r)


def _call(name: str, *args: cst.BaseExpression) -> cst.Call:
    return cst.Call(func=cst.Name(name), args=[cst.Arg(a) for a in args])


def _join(pieces: List[Piece]) -> cst.BaseExpression:
    """``"text" + expr + ...`` from literal text and string expressions."""
    merged: List[Piece] = []
    for piece in pieces:
        if isinstance(piece, str):
            if not piece:
                continue
            if merged and isinstance(merged[-1], str):
                merged[-1] += piece
                continue
        merged.append(piece)
    if not merged:
        return _str("")
    nodes = [_str(p) if isinstance(p, str) else p for p in merged]
    if len(nodes) == 1:
        return nodes[0]
    result = nodes[0]
    for node in nodes[1:]:
        result = cst.BinaryOperation(result, cst.Add(), node)
    return result.with_changes(lpar=[cst.LeftParen()], rpar=[cst.RightParen()])


def _field(
    value: cst.BaseExpression,
    conversion: Optional[str],
    spec: Optional[cst.BaseExpression],
) -> cst.BaseExpression:
    """A str.format()/f-string replacement field as a string expression."""
    if conversion in ("r", "a"):
        value = _call("repr", value)
    elif conversion == "s" or spec is None:
        value = _call("str", value)
    if spec is not None:
        value = _call("format", value, spec)
    return value


def _is_repeatable(node: cst.BaseExpression) -> bool:
    """Safe to evaluate more than once: no calls (or lambdas, etc.)."""
    safe = (
        cst.Name,
        cst.Attribute,
        cst.Subscript,
        cst.SubscriptElement,
        cst.Index,
        cst.BaseString,
        cst.FormattedStringText,
        cst.Integer,
        cst.Float,
        cst.BinaryOperation,
        cst.UnaryOperation,
        cst.BaseBinaryOp,
        cst.BaseUnaryOp,
        cst.Tuple,
        cst.Element,
        cst.LeftParen,
        cst.RightParen,
        cst.BaseParenthesizableWhitespace,
        cst.Comma,
        cst.Dot,
        cst.LeftSquareBracket,
        cst.RightSquareBracket,
    )
    ok = True

    class _Check(cst.CSTVisitor):
        def on_visit(self, n: cst.CSTNode) -> bool:
            nonlocal ok
            if not isinstance(n, safe):
                ok = False
            return ok

    node.visit(_Check())
    return ok


def _literal(node: cst.BaseExpression) -> Optional[str]:
    """Value of a str literal (or literals joined with +), else None."""
    if isinstance(node, cst.SimpleString):
        if "b" in node.prefix.lower():
            return None
        return node.evaluated_value
    if isinstance(node, cst.ConcatenatedString):
        value = node.evaluated_value
        return value if isinstance(value, str) else None
    if isinstance(node, cst.BinaryOperation) and isinstance(node.operator, cst.Add):
        left, right = _literal(node.left), _literal(node.right)
        if left is not None and right is not None:
            return left + right
    return None


class RemoveFStrings(codemod.ContextAwareTransformer):
    """
    Larky has no f-strings:

        f"{x}, {y!r}: {z:>8.2f}"

    becomes:

        (str(x) + ", " + repr(y) + ": " + format(z, ">8.2f"))
    """

    def _spec(self, parts) -> Optional[cst.BaseExpression]:
        if not parts:
            return None
        pieces: List[Piece] = []
        for part in parts:
            if isinstance(part, cst.FormattedStringText):
                pieces.append(part.value)
            else:
                # nested field, e.g. f"{x:{width}}"
                pieces.append(
                    _field(
                        part.expression, part.conversion, self._spec(part.format_spec)
                    )
                )
        return _join(pieces)

    def leave_FormattedString(
        self,
        original_node: cst.FormattedString,
        updated_node: cst.FormattedString,
    ) -> cst.BaseExpression:
        if not any(
            isinstance(p, cst.FormattedStringExpression) for p in updated_node.parts
        ):
            # nothing to do (not a f-string)
            return updated_node
        prefix = updated_node.start[: -len(updated_node.end)].lower()
        if "b" in prefix:
            return updated_node
        raw = "r" in prefix
        pieces: List[Piece] = []
        for part in updated_node.parts:
            if isinstance(part, cst.FormattedStringText):
                text = part.value.replace("{{", "{").replace("}}", "}")
                if not raw:
                    # the text is source code: decode its escapes by reading
                    # it back inside the f-string's own quotes
                    quote = updated_node.end
                    try:
                        text = cst.ensure_type(
                            cst.parse_expression(quote + text + quote),
                            cst.SimpleString,
                        ).evaluated_value
                    except Exception:
                        return updated_node
                pieces.append(text)
                continue
            if part.equal is not None:
                # f"{x=}" -- leave it for a manual port
                return updated_node
            pieces.append(
                _field(part.expression, part.conversion, self._spec(part.format_spec))
            )
        return _join(pieces)


class RewriteStrFormat(codemod.ContextAwareTransformer):
    """
    "...".format(...) with a literal template whose fields use format specs
    or conversions (Starlark's str.format supports only {}, {0} and {name}):

        "{0:>8.2f} {1!r} {name}".format(a, b, name=c)

    becomes:

        (format(a, ">8.2f") + " " + repr(b) + " " + str(c))

    Calls with *args/**kwargs, nested fields in a spec, mixed automatic and
    manual field numbering, or an argument with a call in it that would be
    evaluated other than once are left alone.
    """

    def leave_Call(
        self, original_node: cst.Call, updated_node: cst.Call
    ) -> cst.BaseExpression:
        func = updated_node.func
        if not m.matches(func, m.Attribute(attr=m.Name("format"))):
            return updated_node
        template_text = _literal(func.value)
        if template_text is None:
            return updated_node
        args = updated_node.args
        if any(a.star for a in args):
            return updated_node
        positional = [a.value for a in args if a.keyword is None]
        keywords = {a.keyword.value: a.value for a in args if a.keyword}
        try:
            parsed = list(string.Formatter().parse(template_text))
        except ValueError:
            return updated_node
        if not any(
            spec or conversion
            for _, field, spec, conversion in parsed
            if field is not None
        ):
            # plain {} / {0} / {name} fields are standard Starlark
            return updated_node

        pieces: List[Piece] = []
        used, auto, numbered = [], 0, None
        for literal, field, spec, conversion in parsed:
            pieces.append(literal)
            if field is None:
                continue
            if spec and "{" in spec:
                return updated_node
            first, rest = formatter_field_name_split(field)
            numbering = "auto" if first == "" else "manual"
            if isinstance(first, int) or first == "":
                if numbered not in (None, numbering):
                    # Python raises ValueError; keep that behaviour
                    return updated_node
                numbered = numbering
            if first == "":
                first, auto = auto, auto + 1
            if isinstance(first, int):
                if first >= len(positional):
                    return updated_node
                value, key = positional[first], ("pos", first)
            else:
                if first not in keywords:
                    return updated_node
                value, key = keywords[first], ("kw", first)
            used.append(key)
            for is_attr, item in rest:
                if is_attr:
                    value = cst.Attribute(value, cst.Name(item))
                else:
                    index = (
                        cst.Integer(str(item)) if isinstance(item, int) else _str(item)
                    )
                    value = cst.Subscript(
                        value, [cst.SubscriptElement(cst.Index(index))]
                    )
            pieces.append(_field(value, conversion, _str(spec) if spec else None))

        # Python evaluates each argument once; don't duplicate or drop one
        # that may have side effects.
        every = [("pos", i) for i in range(len(positional))] + [
            ("kw", k) for k in keywords
        ]
        for key in every:
            node = positional[key[1]] if key[0] == "pos" else keywords[key[1]]
            if used.count(key) != 1 and not _is_repeatable(node):
                return updated_node
        return _join(pieces)


_PRINTF = re.compile(
    r"%(?:\((?P<key>[^)]*)\))?"
    r"(?P<flags>[-#0 +]*)"
    r"(?P<width>\*|\d+)?"
    r"(?:\.(?P<precision>\*|\d*))?"
    r"[hlL]?"
    r"(?P<type>.)?",
    re.S,
)


class RewritePercentFormat(codemod.ContextAwareTransformer):
    """
    printf-style formatting with a literal format string:

        "%05.1f|%-5s|%+d|%x|%(k)r" % (a, b, c, d, m)

    becomes:

        (format(a, "05.1f") + "|" + format(str(b), "<5") + "|"
         + format(int(c), "+d") + "|" + format(d, "x") + "|" + repr(m["k"]))

    Left as ``%``: a format string that is not a literal, bytes, %c,
    precision on an integer conversion (%.3d), a right-hand side whose items
    cannot be matched to the conversions, and anything Python would reject.
    """

    _INT = "diu"
    _NUMBER = "oxXeEfFgG"

    @staticmethod
    def _spec(flags, width, precision, ftype, star) -> Piece:
        """The format spec: a str, or an expression when '*' is used."""
        numeric = ftype != ""
        left = "-" in flags
        parts: List[Piece] = []
        if width is not None:
            if left:
                parts.append("<")
            elif not numeric:
                # %5s right-aligns; format() left-aligns strings by default
                parts.append(">")
        if numeric:
            if "+" in flags:
                parts.append("+")
            elif " " in flags:
                parts.append(" ")
            if "#" in flags:
                parts.append("#")
            if "0" in flags and not left and width is not None:
                parts.append("0")
        if width is not None:
            parts.append(star.pop(0) if width == "*" else width)
        if precision is not None:
            parts.append(".")
            parts.append(star.pop(0) if precision == "*" else (precision or "0"))
        parts.append(ftype)
        if all(isinstance(p, str) for p in parts):
            return "".join(parts)
        return _join([p if isinstance(p, str) else _call("str", p) for p in parts])

    def _args(self, rhs: cst.BaseExpression, consumers: int):
        """The positional values for the conversions, or None."""
        if isinstance(rhs, cst.Tuple):
            if any(isinstance(el, cst.StarredElement) for el in rhs.elements):
                return None
            args = [el.value for el in rhs.elements]
        elif consumers == 1:
            # "%s" % x  (Python would unpack x if it were a tuple)
            args = [rhs]
        elif consumers > 1 and _is_repeatable(rhs):
            # "%s-%s" % pair
            args = [
                cst.Subscript(rhs, [cst.SubscriptElement(cst.Index(cst.Integer(str(i))))])
                for i in range(consumers)
            ]
        else:
            return None
        return args if len(args) == consumers else None

    def leave_BinaryOperation(
        self,
        original_node: cst.BinaryOperation,
        updated_node: cst.BinaryOperation,
    ) -> cst.BaseExpression:
        if not isinstance(updated_node.operator, cst.Modulo):
            return updated_node
        fmt = _literal(updated_node.left)
        if fmt is None:
            return updated_node
        rhs = updated_node.right

        directives = []
        pos = fmt.find("%")
        while pos >= 0:
            match = _PRINTF.match(fmt, pos)
            if match is None or match.group("type") is None:
                return updated_node
            directives.append(match)
            pos = fmt.find("%", match.end())

        keyed = [d for d in directives if d.group("key") is not None]
        entries = mapping = None
        args: List[cst.BaseExpression] = []
        if keyed:
            if any(
                d.group("key") is None and d.group("type") != "%" for d in directives
            ) or any("*" in (d.group("width"), d.group("precision")) for d in keyed):
                return updated_node
            if isinstance(rhs, cst.Dict):
                entries = {}
                for el in rhs.elements:
                    key = _literal(el.key) if isinstance(el, cst.DictElement) else None
                    if key is None:
                        return updated_node
                    entries[key] = el.value
            elif _is_repeatable(rhs):
                mapping = rhs
            else:
                return updated_node
        else:
            consumers = sum(
                (d.group("type") != "%")
                + (d.group("width") == "*")
                + (d.group("precision") == "*")
                for d in directives
            )
            args = self._args(rhs, consumers)
            if args is None:
                return updated_node

        pieces: List[Piece] = []
        pos = 0
        for d in directives:
            pieces.append(fmt[pos : d.start()])
            pos = d.end()
            flags, width, precision, ctype = d.group(
                "flags", "width", "precision", "type"
            )
            if ctype == "%":
                pieces.append("%")
                continue
            star = []
            if width == "*":
                star.append(args.pop(0))
            if precision == "*":
                star.append(args.pop(0))
            key = d.group("key")
            if key is None:
                value = args.pop(0)
            elif entries is not None:
                if key not in entries:
                    return updated_node
                value = entries[key]
            else:
                value = cst.Subscript(
                    mapping, [cst.SubscriptElement(cst.Index(_str(key)))]
                )

            if ctype in self._INT:
                if precision is not None:
                    return updated_node
                # %d truncates floats
                value, ftype = _call("int", value), "d"
            elif ctype in self._NUMBER:
                if ctype in "oxX" and precision is not None:
                    return updated_node
                ftype = ctype
            elif ctype in "rsa":
                value = _call("repr" if ctype in "ra" else "str", value)
                ftype = ""
            else:
                # %c, or a conversion Python rejects
                return updated_node
            spec = self._spec(flags, width, precision, ftype, star)
            if spec == "":
                pieces.append(value)
            elif spec == "d":
                pieces.append(_call("str", value))
            else:
                pieces.append(
                    _call("format", value, _str(spec) if isinstance(spec, str) else spec)
                )
        pieces.append(fmt[pos:])
        return _join(pieces)
