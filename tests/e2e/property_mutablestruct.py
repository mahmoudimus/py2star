# options: use_mutablestruct=True
class Foo(object):
    def __init__(self, n):
        self._n = n

    def get_name(self):
        return self._n

    @property
    def name(self):
        return self.get_name()

def main():
    f = Foo("bob")
    print(f.name)

main()

class Temp(object):
    def __init__(self):
        self._c = 0

    @property
    def celsius(self):
        return self._c

    @celsius.setter
    def celsius(self, v):
        self._c = v * 2

    @staticmethod
    def unit():
        return "C"

def main2():
    t = Temp()
    t.celsius = 21
    print(t.celsius, Temp.unit() if False else "C")

main2()
