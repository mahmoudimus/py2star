# options: use_error_not_fail=True, unwrap_errors=True
def f(x):
    if x < 0:
        raise ValueError("neg")
    return x

def main():
    try:
        f(-1)
    except ValueError as e:
        print("caught", str(e))
    print(f(2))

main()
