def gen(n):
    for i in range(n):
        yield i * 2

def gen2(xs):
    yield 0
    yield from xs
    yield 99

def evens(xs):
    for x in xs:
        if x % 2:
            continue
        yield x

def main():
    print(list(gen(4)))
    print([x for x in gen2([1, 2])])
    print(sum(evens([1, 2, 3, 4])))

main()
