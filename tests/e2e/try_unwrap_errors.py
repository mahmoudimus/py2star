# options: use_error_not_fail=True, unwrap_errors=True
def lookup(d, k):
    try:
        v = d[k]
    except KeyError:
        v = -1
    return v

def lookup_ret(d, k):
    try:
        return d[k]
    except (KeyError, IndexError):
        return None

def with_finally(xs, log):
    total = 0
    try:
        for x in xs:
            total += x
    finally:
        log.append("finally %d" % total)
    return total

def with_else(d, k, log):
    try:
        v = d[k]
    except KeyError:
        log.append("missing")
        v = 0
    else:
        log.append("found")
    finally:
        log.append("done")
    return v

def custom(x):
    if x < 0:
        raise ValueError("negative: %d" % x)
    return x * 2

def catch_custom(x):
    try:
        r = custom(x)
    except ValueError as e:
        r = str(e)
    return r

def reraise(d):
    try:
        return d["a"]
    except KeyError:
        raise

def loop_break(items):
    out = []
    for it in items:
        try:
            if it == "stop":
                break
            if it == "skip":
                continue
            out.append(int(it))
        except ValueError:
            out.append(-1)
    return out

def nested(d):
    try:
        try:
            return d["x"]["y"]
        except KeyError:
            return d["z"]
    except KeyError:
        return "none"

def div(a, b):
    try:
        return a // b
    except ZeroDivisionError:
        return 0

def reraise_caught():
    try:
        reraise({})
    except KeyError:
        return "reraised"

def raise_in_else(log):
    try:
        log.append("body")
    except KeyError:
        log.append("never")
    else:
        raise ValueError("from else")

def main():
    print(lookup({"a": 1}, "a"), lookup({}, "a"))
    print(lookup_ret({"a": 1}, "a"), lookup_ret({}, "a"))
    log = []
    print(with_finally([1, 2, 3], log), log)
    log = []
    print(with_else({"a": 5}, "a", log), with_else({}, "a", log), log)
    print(catch_custom(3), catch_custom(-2))
    print(loop_break(["1", "x", "skip", "4", "stop", "9"]))
    print(nested({"x": {"y": 1}}), nested({"z": 2}), nested({}))
    print(div(7, 2), div(1, 0))
    print(reraise({"a": 3}))
    print(reraise_caught())
    log = []
    try:
        raise_in_else(log)
    except ValueError as e:
        print("else raised:", e, log)

main()
