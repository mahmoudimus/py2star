# options: use_mutablestruct=True
class Account(object):
    """An account."""
    LIMIT = 100

    def describe(self):
        return self.owner + ":" + str(self.balance)

    def __init__(self, owner, balance=0):
        self.owner = owner
        self.balance = self.clamp(balance)
        self.label = self.describe()

    def clamp(self, amount):
        if amount > self.LIMIT:
            return self.LIMIT
        return amount


class NoInit(object):
    GREETING = "hi"

    def greet(self, name):
        return self.GREETING + " " + name


def main():
    a = Account("al", 250)
    print(a.label, a.LIMIT, Account("bo").describe())
    print(NoInit().greet("cy"))


main()
