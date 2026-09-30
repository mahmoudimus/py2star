"""
String formatting Larky does not support: f-strings, and format specs or
conversions in str.format() fields. Both become % formatting, which Larky
implements as Python does; a field with a format spec goes through the
format() built-in.
"""
import string
from _string import formatter_field_name_split
from typing import List, Optional, Union

import libcst as cst
import libcst.matchers as m
from libcst import codemod


def _str(value: str) -> cst.SimpleString:
    """A double-quoted string literal for value."""
    r = repr(value)
    if r[0] == "'":
        r = '"' + r[1:-1].replace("\\'", "'").replace('"', '\\"') + '"'
    return cst.SimpleString(r)


def _call(name: str, *args: cst.BaseExpression) -> cst.Call:
    return cst.Call(func=cst.Name(name), args=[cst.Arg(a) for a in args])


def _field(
    value: cst.BaseExpression,
    conversion: Optional[str],
    spec: Optional[cst.BaseExpression],
) -> cst.BaseExpression:
    """The value of one replacement field, ready for a %s."""
    if conversion in ("r", "a"):
        value = _call("repr", value)
    elif conversion == "s":
        value = _call("str", value)
    if spec is not None:
        value = _call("format", value, spec)
    return value


def _percent(template: str, fields: List[cst.BaseExpression]) -> cst.BaseExpression:
    return cst.BinaryOperation(
        left=_str(template),
        operator=cst.Modulo(),
        right=cst.Tuple([cst.Element(f) for f in fields]),
        lpar=[cst.LeftParen()],
        rpar=[cst.RightParen()],
    )


class RemoveFStrings(codemod.ContextAwareTransformer):
    """
    Larky has no f-strings:

        f"{x}, {y!r}: {z:>8.2f}"

    becomes:

        ("%s, %s: %s" % (x, repr(y), format(z, ">8.2f")))
    """

    def _spec(self, parts) -> Optional[cst.BaseExpression]:
        if not parts:
            return None
        pieces: List[cst.BaseExpression] = []
        for part in parts:
            if isinstance(part, cst.FormattedStringText):
                pieces.append(_str(part.value))
            else:
                # nested field, e.g. f"{x:{width}}"
                pieces.append(
                    _call(
                        "str", _field(part.expression, part.conversion, None)
                    )
                )
        spec = pieces[0]
        for piece in pieces[1:]:
            spec = cst.BinaryOperation(spec, cst.Add(), piece)
        return spec

    def leave_FormattedString(
        self,
        original_node: cst.FormattedString,
        updated_node: cst.FormattedString,
    ) -> Union[cst.FormattedString, cst.BinaryOperation]:
        if not any(
            isinstance(p, cst.FormattedStringExpression)
            for p in updated_node.parts
        ):
            # nothing to do (not a f-string)
            return updated_node
        prefix = updated_node.start[:-len(updated_node.end)].lower()
        if "b" in prefix:
            return updated_node
        raw = "r" in prefix
        template, fields = "", []
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
                template += text.replace("%", "%%")
                continue
            if part.equal is not None:
                # f"{x=}" -- leave it for a manual port
                return updated_node
            template += "%s"
            fields.append(
                _field(part.expression, part.conversion, self._spec(part.format_spec))
            )
        return _percent(template, fields)


class RewriteStrFormat(codemod.ContextAwareTransformer):
    """
    Larky's str.format() supports {}, {0} and {name} fields but not format
    specs or conversions; calls that use them become % formatting:

        "{0:>8.2f} {1!r} {name}".format(a, b, name=c)

    becomes:

        ("%s %s %s" % (format(a, ">8.2f"), repr(b), c))

    Calls with *args/**kwargs, nested fields in a spec, or an argument with
    side effects used more than once are left alone.
    """

    @staticmethod
    def _literal(node: cst.BaseExpression) -> Optional[str]:
        """Value of a str literal (or literals joined with +), else None."""
        if isinstance(node, cst.SimpleString):
            if "b" in node.prefix.lower():
                return None
            return node.evaluated_value
        if isinstance(node, cst.ConcatenatedString):
            value = node.evaluated_value
            return value if isinstance(value, str) else None
        if isinstance(node, cst.BinaryOperation) and isinstance(
            node.operator, cst.Add
        ):
            left = RewriteStrFormat._literal(node.left)
            right = RewriteStrFormat._literal(node.right)
            if left is not None and right is not None:
                return left + right
        return None

    @staticmethod
    def _simple(node: cst.BaseExpression) -> bool:
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

    def leave_Call(
        self, original_node: cst.Call, updated_node: cst.Call
    ) -> cst.BaseExpression:
        func = updated_node.func
        if not m.matches(func, m.Attribute(attr=m.Name("format"))):
            return updated_node
        template_text = self._literal(func.value)
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
            # plain {} / {0} / {name} fields: Larky handles these
            return updated_node

        template, fields, used, auto, numbered = "", [], [], 0, None
        for literal, field, spec, conversion in parsed:
            template += literal.replace("%", "%%")
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
                        cst.Integer(str(item))
                        if isinstance(item, int)
                        else _str(item)
                    )
                    value = cst.Subscript(
                        value, [cst.SubscriptElement(cst.Index(index))]
                    )
            template += "%s"
            fields.append(
                _field(
                    value,
                    conversion,
                    _str(spec) if spec else None,
                )
            )

        # Python evaluates each argument once; don't duplicate or drop one
        # that may have side effects.
        every = [("pos", i) for i in range(len(positional))] + [
            ("kw", k) for k in keywords
        ]
        for key in every:
            node = positional[key[1]] if key[0] == "pos" else keywords[key[1]]
            if used.count(key) != 1 and not self._simple(node):
                return updated_node
        return _percent(template, fields)
