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
