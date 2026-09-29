def f(d, log):
    try:
        return d["a"]
    except KeyError:
        log.append("handler")
        raise
    finally:
        log.append("finally")

def g(log):
    try:
        raise ValueError("x")
    except ValueError:
        raise KeyError("y")
    finally:
        log.append("g finally")

def main():
    log = []
    print(f({"a": 1}, log), log)
    log = []
    try:
        f({}, log)
    except KeyError:
        print("reraised", log)
    log = []
    try:
        g(log)
    except KeyError:
        print("g", log)

main()

def h(d, log):
    try:
        v = d["k"]
    except KeyError:
        return "missing"
    else:
        return v
    finally:
        log.append("h finally")

def main2():
    log = []
    print(h({}, log), h({"k": 2}, log), log)
main2()
