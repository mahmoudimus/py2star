# options: use_mutablestruct=True
class Counter(object):
    def __init__(self, start=0, *args, **kwargs):
        self.n = start
        self.args = args
        self.kwargs = kwargs

    def add(self, amount):
        self.n += amount
        return self.n

    def increment(self):
        return self.add(1)

    @property
    def value(self):
        return self.n

    @value.setter
    def value(self, n):
        self.n = n


def main():
    default = Counter()
    overridden = Counter(5)
    extra = Counter(1, 2, 3, k=4)
    print(default.n, overridden.n)
    print(extra.n, extra.args, extra.kwargs)
    print(default.increment(), overridden.increment())
    extra.value = 10
    print(extra.value, extra.increment(), extra.value)
    print(default.value, overridden.value)


main()
