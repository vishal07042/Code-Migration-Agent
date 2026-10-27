const { addDays, dayOfWeekUtc } = require("./dates");

test("addDays", () => {
  expect(addDays("2026-05-06", 3)).toBe("2026-05-09T00:00:00.000Z");
  expect(addDays("2026-01-01", -1)).toBe("2025-12-31T00:00:00.000Z");
  expect(() => addDays("garbage", 1)).toThrow();
});

test("dayOfWeekUtc", () => {
  expect(dayOfWeekUtc("2026-05-06")).toBe(3);
  expect(dayOfWeekUtc("2026-05-10")).toBe(0);
});
