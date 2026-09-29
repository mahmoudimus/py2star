def find(xs, target):
    for i, x in enumerate(xs):
        if x == target:
            print("found at", i)
            break
    else:
        print("not found")

def nested(grid):
    for row in grid:
        for c in row:
            if c < 0:
                break
        else:
            print("row ok", row)

def wloop(n):
    i = 0
    while i < n:
        if i == 10:
            break
        i += 1
    else:
        print("while else", i)

def main():
    find([1, 2, 3], 2)
    find([1, 2, 3], 5)
    nested([[1, 2], [3, -1], [4]])
    wloop(3)
    wloop(20)

main()
