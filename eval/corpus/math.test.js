const { add, clamp, factorial } = require("./math");

test("add", () => {
  expect(add(2, 3)).toBe(5);
  expect(add(-1, 1)).toBe(0);
  expect(add(0.5, 0.25)).toBe(0.75);
});

test("clamp", () => {
  expect(clamp(5, 0, 10)).toBe(5);
  expect(clamp(-2, 0, 10)).toBe(0);
  expect(clamp(99, 0, 10)).toBe(10);
});

test("factorial", () => {
  expect(factorial(0)).toBe(1);
  expect(factorial(5)).toBe(120);
});
