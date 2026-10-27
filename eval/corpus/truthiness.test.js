const { toLabel } = require("./truthiness");

test("toLabel", () => {
  expect(toLabel([])).toBe("yes");
  expect(toLabel("0")).toBe("yes");
  expect(toLabel({})).toBe("yes");
  expect(toLabel(0)).toBe("no");
  expect(toLabel("")).toBe("no");
  expect(toLabel(null)).toBe("no");
  expect(toLabel(undefined)).toBe("no");
});
