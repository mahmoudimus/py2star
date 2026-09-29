import codecs

def main():
    names = ["a", "b"]
    print(sorted(dict.fromkeys(names, 0).items()))
    print(sorted(dict.fromkeys(names).items()))
    b = bytearray(len(names) + 1)
    print(len(bytearray(4)), len(b), b[0], b[2])
    print(codecs.encode(b"hi", "hex") == b"6869", codecs.decode(b"6869", "hex") == b"hi")
    s = "caf"
    e = s.encode("utf-8")
    print(len(e), e[0], e == b"caf")
    q = [1, 2, 0, 3]
    x = None
    while True:
        x = q.pop()
        if not x:
            break
    print(x, q)
    lit = {3, 1}
    comp = {x % 2 for x in [1, 2, 3]}
    print(sorted(lit), sorted(comp))
    print(list(map(lambda v: v * 2, [1, 2])), list(filter(None, [0, 1, 2])))
    print(list(filter(lambda v: v > 1, [1, 2, 3])), sum([1, 2, 3]))
    t = set([1, 2])
    t.add(3)
    print(sorted(t), len(frozenset([1, 1, 2])))

main()
