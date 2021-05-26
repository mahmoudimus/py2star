import ast


class RemoveFStrings(ast.NodeTransformer):
    """Turns f-strings to format syntax with modulus
    ('a = %4d; b = %s;' % ((1 + 1), b))
    """

    def visit_JoinedStr(self, node):
        if not any(
            isinstance(value, ast.FormattedValue) for value in node.values
        ):
            # nothing to do (not a f-string)
            return node
        base_str = ""
        elements = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                base_str += value.value.replace("%", "%%")
            elif isinstance(value, ast.FormattedValue):
                base_str += "%"
                if value.format_spec is None:
                    # if there is no format_spec, lets just convert it to %s
                    base_str += "s"
                    # raise SyntaxError(
                    #     "f-strings without format specifier not supported",
                    #     ("<string>", value.lineno, value.col_offset,"????")
                    # )
                else:
                    base_str += value.format_spec.values[0].value
                elements.append(value.value)
            else:
                raise NotImplementedError

        return ast.BinOp(
            left=ast.Constant(value=base_str, kind=None),
            op=ast.Mod(),
            right=ast.Tuple(elts=elements, ctx=ast.Load()),
        )
