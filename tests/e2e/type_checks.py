def kind(x):
    if type(x) is str:
        return "str"
    if type(x) == dict:
        return "dict"
    if type(x) is not list:
        return "other"
    return "list"

def main():
    print(kind("a"), kind({}), kind([]), kind(1))

main()
