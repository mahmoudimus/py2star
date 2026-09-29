def main():
    x = [1, 2, 3, 4, 5]
    x[1:3] = [9, 9, 9]
    print(x)
    y = x
    x[:] = []
    print(x, y)
    z = [1, 2, 3, 4, 5, 6]
    z[-2:] = ["a"]
    print(z)
    z[:2] = []
    print(z)
    i, j = 1, 2
    z[i:j] = [7, 8]
    print(z)
    d = {"a": 1, "b": 2, "c": 3}
    del d["a"], d["b"]
    print(d)
    w = [0, 1, 2, 3, 4, 5, 6]
    del w[1:3]
    print(w)
    del w[:2]
    print(w)
    del w[-1]
    print(w)
    del w[i + 1:]
    print(w)

main()
