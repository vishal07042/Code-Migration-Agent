"""Reference conversion of eval/corpus/math.js (verified: static clean, 100% diff)."""


def add(a: float, b: float) -> float:
    return a + b


def clamp(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def factorial(n: int) -> int:
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("factorial: non-negative integer expected")
    if n < 0:
        raise ValueError("factorial: non-negative integer expected")
    r = 1
    for i in range(2, n + 1):
        r *= i
    return r
