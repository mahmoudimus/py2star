def counter():
    count = 0
    def inc(by):
        nonlocal count
        count += by
        return count
    inc(2)
    inc(3)
    return count

def two():
    a, b = 1, 2
    def swap():
        nonlocal a, b
        a, b = b, a
    swap()
    return a, b

def main():
    print(counter())
    print(two())

main()

def shadow():
    x = 1
    def inner():
        nonlocal x
        x = x + 1
        def deeper():
            x = 100
            return x
        return deeper()
    def reader():
        return x * 10
    return inner(), reader(), x

def param_owner(n):
    def bump():
        nonlocal n
        n += 1
    bump()
    bump()
    return n

print(shadow(), param_owner(5))
