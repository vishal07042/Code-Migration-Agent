const { unique, sortedNumeric, flattenOnce } = require("./arrays");

test("unique", () => {
  expect(unique([1, 2, 2, 3, 1])).toEqual([1, 2, 3]);
  expect(unique([])).toEqual([]);
  expect(unique(["a", "a", "b"])).toEqual(["a", "b"]);
});

test("sortedNumeric", () => {
  expect(sortedNumeric([10, 9, 80])).toEqual([9, 10, 80]);
  expect(sortedNumeric([3, 1, 2])).toEqual([1, 2, 3]);
});

test("flattenOnce", () => {
  expect(flattenOnce([[1, 2], [3]])).toEqual([1, 2, 3]);
  expect(flattenOnce([1, [2, [3]]])).toEqual([1, 2, [3]]);
});
