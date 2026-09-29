from typing import Union

import libcst as cst
from libcst import codemod


class RemoveFStrings(codemod.ContextAwareTransformer):
    """Turns f-strings to format syntax with modulus
    ('a = %4d; b = %s;' % ((1 + 1), b))
    """

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
        base_str = ""
        elements = []
        for part in updated_node.parts:
            if isinstance(part, cst.FormattedStringText):
                text = part.value.replace("{{", "{").replace("}}", "}")
                base_str += text.replace("%", "%%")
                continue
            spec = part.format_spec
            if spec is None:
                # if there is no format_spec, lets just convert it to %s
                base_str += "%r" if part.conversion == "r" else "%s"
            elif all(isinstance(s, cst.FormattedStringText) for s in spec):
                base_str += "%" + "".join(s.value for s in spec)
            else:
                # nested replacement fields in the format spec have no
                # %-format equivalent
                return updated_node
            elements.append(cst.Element(part.expression))

        # keep any string prefix other than "f" (e.g. r"...")
        prefix = updated_node.start[:-1].replace("f", "").replace("F", "")
        quote = updated_node.end
        return cst.BinaryOperation(
            left=cst.SimpleString(f"{prefix}{quote}{base_str}{quote}"),
            operator=cst.Modulo(),
            right=cst.Tuple(elements),
            lpar=[cst.LeftParen()],
            rpar=[cst.RightParen()],
        )
