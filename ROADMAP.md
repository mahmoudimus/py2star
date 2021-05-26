 # TODO
 
### imports     

- from Crypto.PublicKey import RSA => load("@vendor//Crypto/PublicKey/RSA", "RSA")
- relative imports: 
  - from .base import y => load("@vendor//pkgname/base/y", y="y")

- warn on unknown symbols
  - potential corner case: self.xx in dedented functions not in an enclosing function

### desugaring

- decorators should be desugared
- set literals should be desugared from {} to sets.make()
  In [3]: ast.dump(ast.parse("""set([1, 2])"""))
  Out[3]: "Module(body=[Expr(value=Call(func=Name(id='set', ctx=Load()), args=[List(e
  lts=[Constant(value=1, kind=None), Constant(value=2, kind=None)], ctx=Load())], key
  words=[]))], type_ignores=[])"
  
  In [4]: ast.dump(ast.parse("""set(1, 2)"""))
  Out[4]: "Module(body=[Expr(value=Call(func=Name(id='set', ctx=Load()), args=[Consta
  nt(value=1, kind=None), Constant(value=2, kind=None)], keywords=[]))], type_ignores
  =[])"
  
- 

### complex translations

- rewrite try/except statements

- Rewrite lib2to3 fixers to libcst

- integrate lib3to6?
  
- rewrite:
    - a = b = "xyz" to:
      - a = "xyz"
      - b = a

### exceptions

- Exceptions => fail(), fix up the strings
  - fail("TypeError(\"xxxxxx\")") => fail("TypeError: xxxxxx")
  - test string formatting cases as well
    

### operators

- ** to pow
- X @ Y = operator.matmul(x,y)..


### bytes:
  
  - if byte literals are in ascii range, do not escape them by converting them to 
    hex digits 
    
    i.e. bytes([0x70, 0x61, 0x73, 0x73, 0x77, 0x6F, 0x72, 0x64]) == bytes("password", encoding="utf-8") == b"password"

### misc:

- remove if __name__ == '__main__'..

-  if methods are referenced in the class, then they should be ordered so that 
   they are defined first before invoking them in init? test this!
