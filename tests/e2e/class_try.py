# options: use_mutablestruct=True
class Store(object):
    def __init__(self, data):
        def pick(k):
            return data.get(k, 0)
        try:
            self.first = data["first"]
        except KeyError:
            self.first = pick("alt")

    def get(self, k):
        try:
            return self.first + k
        except TypeError:
            return -1

def main():
    s = Store({"first": 1})
    t = Store({"alt": 7})
    print(s.first, t.first, s.get(2), s.get("x"))

main()
