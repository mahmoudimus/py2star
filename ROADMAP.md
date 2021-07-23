 # Roadmap

### string formatting

- `return "".join(["%02x" % bord(x) for x in self.digest()])` "%02x" is not supported :(
- `larky.strings.zfill`
- `if not (4 <= cost) and (cost <= 31)` => `if not ((4 <= cost) and (cost <= 31))`
- `int(b'1', 2)`


### imports     

- [ ] from Crypto.PublicKey import RSA => load("@vendor//Crypto/PublicKey/RSA", "RSA")
- [x] relative imports:
  - [x] from .base import y => load("@vendor//pkgname/base/y", y="y")  

- [ ] warn on unknown symbols?
- [ ] potential corner case: self.xx in dedented functions not in an enclosing function

### desugaring

- [x] decorators should be desugared
- [x] set literals should be desugared from {} to sets.make()

### complex translations

- [x] sort imports so that they come *before* anything else in the file 
- [x] solve the from . import X case
- [x] del
- [x] rewrite:
    - [x] a = b = "xyz" to:
        - a = "xyz"
        - b = a  
- [ ] rewrite try/except statements
- [ ] with statements
- [ ] `yield from` => `return`  

- [ ] 
```python
def do(namespace): 
    if not namespaces:
        raise KeyError  # gets translated to return KeyError! WRONG!
```

- [x] for non-tests, rewrite `assert self._last.tail == None, "internal error (tail)"` to
      the inverse `if not (self._last.tail == None): ...`

- [ ] `type(text).__name__` or `type(text).__class__.__name__` needs to be changed to `type(text)`
- [ ] for/else (replace)
- [x] `_WHILE_LOOP_EMULATION_ITERATION` => `WHILE_LOOP_EMULATION_ITERATION` instead
- [ ] `events[:index] = []` == `for i in range(index): events.pop(0)` 

    
- [x] decode()/encode() should be translated to codecs.encode()/codecs.decode()
- [x] `self.__class__` => `__init__()` or `function()...`
- [] migrate this:
```python
    class ParseError(SyntaxError):
        """An error when parsing an XML document.
    
        In addition to its exception value, a ParseError contains
        two extra attributes:
            'code'     - the specific exception code
            'position' - the line and column of the error
    
        """
    
        pass
``` 
  to:

```python
    def ParseError(code, position):
        """An error when parsing an XML document.
    
        In addition to its exception value, a ParseError contains
        two extra attributes:
            'code'     - the specific exception code
            'position' - the line and column of the error
    
        """
        return Error("ParseError: (code: %s) (position: %s)" % (code, position))
```
- [] `elem[:] = class w/ __getitem__` to `??`
- [] `warnings` => `??` (delete or print?)
- [] migrate:

```python
def foo(target):
    try:
        close_handler = target.close
    except AttributeError:
        pass
    else:
        return close_handler()
    finally:
        del target
```

- [x] implicit string concatanation..

## bug fixes

- [x] `__class__` vs `__name__` (oops!, i misunderstood semantics..)

### exceptions

- [x] Exceptions => fail(), fix up the strings
  - [x] test string formatting cases as well
    
- [ ] ~~fail("TypeError(\"xxxxxx\")") => fail("TypeError: xxxxxx")~~
- [x] with introduction of `Error` `Ok` object, we no longer need to fail()

### operators

- [x] ** to pow

### bytes:
  
- [x] starlark bytes support was merged into starlarky (upstream!) 
  
    - if byte literals are in ascii range, do not escape them by converting them to 
      hex digits 
      
      i.e. bytes([0x70, 0x61, 0x73, 0x73, 0x77, 0x6F, 0x72, 0x64]) == bytes("password", encoding="utf-8") == b"password"

### misc:

- [x] remove if __name__ == '__main__'..

- [ ] if methods are referenced in the class, then they should be ordered so that 
   they are defined first before invoking them in init? test this!
   

## TODO

- [x] integrate lib3to6
- [ ] python-future?
- ~~pybackwards has issues (astunparse)~~

```python
attr_value = elem.get(key)
if attr_value != None and attr_value != value:
```
- the cli should really be something similar to [instagram/fixit](https://github.com/instagram/fixit)

More transform desugaring ideas here:
- [pydron](https://github.com/pydron/pydron/tree/master/pydron/translation/dedecorator.py)
- [pythran](https://github.com/serge-sans-paille/pythran/tree/master/pythran/transformations)
- [typy](https://github.com/Procrat/typy/blob/master/typy/insuline.py)
  
- [x] Rewrite lib2to3 fixers to libcst
  - [x] Particularly the test generation stuff should be easy to port tests

## Ideas

```python
class Algo:
   x = 1
   y = 2
```

should just be migrated to a module called `Algo` with globals of x and y
