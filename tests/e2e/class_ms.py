# options: use_mutablestruct=True
class Foo(object):
    def __init__(self, n):
        self._n = n

    def get_name(self):
        return self._n

def main():
    f = Foo("bob")
    print(f.get_name())

main()
