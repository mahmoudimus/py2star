## Scatch ideas      

Transform code by slicing position via text

```python
print(z.code)
code = updated_node.code_for_node(updated_node)
x = "".join(updated_node.code_for_node(l) for l in self._herp)
zz = "".join(
    [
        code[: self._startpos.line],
        "".join(updated_node.code_for_node(l) for l in self._herp),
        code[self._endpos.line + 1 :],
    ]
)
return updated_node.with_changes(body=cst.parse_module(zz).body)
```
