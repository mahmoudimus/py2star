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