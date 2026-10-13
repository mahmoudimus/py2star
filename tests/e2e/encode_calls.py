class Codec(object):
    def __init__(self, prefix):
        self.prefix = prefix

    def encode(self, value, sep, upper=False):
        out = self.prefix + sep + value
        return out.upper() if upper else out


def main():
    c = Codec("p")
    print(c.encode("v", "-", upper=True))
    print(c.encode("v", ":"))
    data = "hello".encode("utf-8")
    print(len(data), data == "hello".encode(), data == b"hello")
    # an instance of Codec: never str.encode, even with codec-like literals
    print(c.encode("utf-8", "strict"))
    # a known str with a variable encoding
    enc = "utf-8"
    text = "a" + str(7)
    print(text.encode(enc) == b"a7")


main()
