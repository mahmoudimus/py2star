 # Roadmap


### imports     

- [ ] from Crypto.PublicKey import RSA => load("@vendor//Crypto/PublicKey/RSA", "RSA")
- [x] relative imports: 
  1. from .base import y => load("@vendor//pkgname/base/y", y="y")  

- [ ] warn on unknown symbols
  1. potential corner case: self.xx in dedented functions not in an enclosing function

### desugaring

- [x] decorators should be desugared
- [x] set literals should be desugared from {} to sets.make()

More transform desugaring ideas here:
- [pydron](https://github.com/pydron/pydron/tree/master/pydron/translation/dedecorator.py)
- [pythran](https://github.com/serge-sans-paille/pythran/tree/master/pythran/transformations)
- [typy](https://github.com/Procrat/typy/blob/master/typy/insuline.py)
  
### complex translations

- rewrite try/except statements
- [x] sort imports so that they come *before* anything else in the file 
- [x] solve the from . import X case
- with statements
- del 
- Rewrite lib2to3 fixers to libcst
 - Particularly the test generation stuff should be easy to port tests

- for/else (replace)

- [x] rewrite:
    - [x] a = b = "xyz" to:
        - a = "xyz"
        - b = a
    
- decode()/encode() should be translated to codecs.encode()/codecs.decode()

### exceptions

- [x] Exceptions => fail(), fix up the strings
  - [x] test string formatting cases as well
    
- [ ] ~~fail("TypeError(\"xxxxxx\")") => fail("TypeError: xxxxxx")~~
  - [x] with introduction of `Error` `Ok` object, we no longer need to fail()

### operators

- [x] ** to pow
- [ ] X @ Y = operator.matmul(x,y)..


### bytes:
  
- [x] starlark bytes support was merged into starlarky (upstream!) 
  
    - if byte literals are in ascii range, do not escape them by converting them to 
      hex digits 
      
      i.e. bytes([0x70, 0x61, 0x73, 0x73, 0x77, 0x6F, 0x72, 0x64]) == bytes("password", encoding="utf-8") == b"password"

### misc:

- remove if __name__ == '__main__'..

-  if methods are referenced in the class, then they should be ordered so that 
   they are defined first before invoking them in init? test this!
   

## TODO

- integrate lib3to6 / pybackwards / python-future?
- the cli should really be something similar to [instagram/fixit](https://github.com/instagram/fixit)


## Ideas

```python
class Algo:
   x = 1
   y = 2
```

should just be migrated to a module called `Algo` with globals of x and y
