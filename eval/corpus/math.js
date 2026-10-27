/**
 * Pure math helpers (eval corpus).
 */

/**
 * @param {number} a
 * @param {number} b
 */
function add(a, b) {
  return a + b;
}

/**
 * @param {number} x
 * @param {number} lo
 * @param {number} hi
 */
function clamp(x, lo, hi) {
  if (x < lo) return lo;
  if (x > hi) return hi;
  return x;
}

/**
 * @param {number} n
 */
function factorial(n) {
  if (!Number.isInteger(n) || n < 0) throw new Error("factorial: non-negative integer expected");
  let r = 1;
  for (let i = 2; i <= n; i++) r *= i;
  return r;
}

module.exports = { add, clamp, factorial };
