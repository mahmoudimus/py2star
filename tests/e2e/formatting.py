def main():
    x, name, ratio, n = 255, "bob", 2.0 / 3, 7
    width = 6
    print(f"{x:02x}|{x:#010b}|{name!r}|{name:>6}|{ratio:.3f}|{n:{width}d}|100%")
    print(f"{x:,}|{-ratio:+.2e}|{{braces}}|{n!s:^5}|{name:*<{width}}")
    print("{:02x}|{!r}|{who:>5}".format(x, name, who="al"))
    print("{0:X}|{1!r:>7}|{0:o}".format(x, name))
    print("{0:x}{0:X} {1}".format(n + 3, "plain"))
    print("{}-{}".format("plain", "fields"))
    print("%05.1f|%-5s|%+d" % (ratio * 100, "ab", n))
    print("%(k)s=%(v)03d" % {"k": "key", "v": n})

main()


def percent():
    x, s, f, big = 255, "ab", -2.5, 2 ** 70
    print("%5s|%-5s|%.1s|%r|%%|%s" % (s, s, s, s, (1, 2)))
    print("%d|%i|%u|%+d|% d|%05d|%-5d|%x|%#X|%o|%#o" % (x, x, x, x, x, -x, x, x, x, x, x))
    print("%f|%.2f|%+.3e|%G|%g|%10.4f|%-10.1f|%010.2f" % (f, f, f, f, 1e-7, f, f, f))
    print("%d %x" % (big, big))
    print("%*d|%-*.*f|" % (6, 42, 8, 2, 3.14159))
    print("%(name)s is %(age)03d, %(name)r" % {"name": "al", "age": 7})
    print("value: %s" % x)
    print("%d%%" % 3.9)

percent()
