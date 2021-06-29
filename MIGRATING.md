# Migrating Python to Larky

While `py2star` attempts to make porting as automated as possible, there are many scenarios where
there should manual intervention is needed because there's a possible change of semantics.

This document is to serve as a potential pattern repository for migrations.

## Patterns

## `dict.copy()`

```python
attrib = attrib.copy()
attrib.update(extra)
```
can be re-written:

```python
attrib = dict(**attrib)
attrib.update(extra)
```
### Try/Except 

#### Are exceptions even needed? 

You can write this differently:

```python
try:
    name = self._names[key]
except KeyError:
    name = key
    if "}" in name:
        name = "{" + name
    self._names[key] = name
return name
```

without exceptions:

```python
if key in self._names:
    return self._names[key]

name = key
if "}" in name:
    name = "{" + name
self._names[key]= name
return name
```

### Custom Protocol Operators

[Larky](https://github.com/verygoodsecurity/starlarky) has introduced a `stdlib/operator.star` to
mimic Python's operator module. Using that module can allow emulation of
custom operation overloading that *also* works with Python itself.

For example:

```python
class QName():
  def __le__(self, other):
      if isinstance(other, QName):
          return self.text <= other.text  # operator.lte(...)
      return self.text <= other  # operator.lte( .. )
```

can be ported to:

```python
def QName():
    self = larky.mutablestruct(__name__='QName')
    def __le__(other):
        if types.is_instance(other, QName):
            return operator.lte(self.text, other.text)
        return operator.lte(self.text, other)
```

#### Matrix Multiplying

Python introduced a new operator `@` that allows matrix multiplication. Larky
allows this using the `__matmul__` dunder method. So:

```python
X = X @ Y
```

can be:

```python
X = operator.matmul(X, Y)
```

### Recursion/DFS

Starlarky does not allow recursive call, so we use BFS/iteration instead:

```python
class Element:
    def iter(self, tag=None):
        if tag == "*":
            tag = None
        if tag is None or self.tag == tag:
            yield self
        for e in self._children:
            yield from e.iter(tag)
    

def select_child(result):
    for elem in result:
        for e in elem.iter():
            if e is not elem:
                yield e

```

can be:

```python
class Element:
    # remove recursive method
    # def iter(self, tag=None):
    #     if tag == "*":
    #         tag = None
    #     if tag is None or self.tag == tag:
    #         yield self
    #     for e in self._children:
    #         yield from e.iter(tag)

def traverse_descendant(e, tag, rval):
    qu = e._children[0:] # duplicate arr
    for _ in range(_WHILE_LOOP_EMULATION_ITERATION):
        if len(qu) == 0:
            break
        current = qu.pop(0)
        if tag == None or tag == '*' or current.tag == tag:
            rval.append(current)
        qu.extend(current._children)

def select_child(result):
    rval = []
    for e in result:
        traverse_descendant(e, None, rval)
    return rval
```