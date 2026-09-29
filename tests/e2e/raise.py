def msg_format(name, args):
    raise TypeError(
        "{} takes at most 1 positional argument"
        " ({} given)".format(name, len(args))
    )

def msg_name(m):
    raise ValueError(m)

def msg_none():
    raise KeyError("k")

def msg_concat(x):
    raise ValueError("bad " + x)

def msg_percent(x):
    raise ValueError("bad %s" % x)

def check(fn, *args):
    try:
        fn(*args)
    except (TypeError, ValueError, KeyError) as e:
        print("raised", str(e).strip("'"))

def main():
    check(msg_format, "f", [1, 2])
    check(msg_name, "boom")
    check(msg_none)
    check(msg_concat, "x")
    check(msg_percent, "y")

main()
