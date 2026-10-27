const { capitalize, repeat, words } = require("./strings");

test("capitalize", () => {
  expect(capitalize("hello")).toBe("Hello");
  expect(capitalize("")).toBe("");
  expect(capitalize("aBC")).toBe("ABC");
});

test("repeat", () => {
  expect(repeat("ab", 3)).toBe("ababab");
  expect(repeat("x", 0)).toBe("");
});

test("words", () => {
  expect(words("  a  b c ")).toEqual(["a", "b", "c"]);
  expect(words("")).toEqual([]);
  expect(words("solo")).toEqual(["solo"]);
});
