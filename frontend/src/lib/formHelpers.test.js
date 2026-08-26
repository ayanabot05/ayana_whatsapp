import { cleanHabits } from "./formHelpers";

describe("formHelpers", () => {
  describe("cleanHabits", () => {
    test("returns undefined if habits is falsy", () => {
      expect(cleanHabits(null)).toBeUndefined();
      expect(cleanHabits(undefined)).toBeUndefined();
    });

    test("cleans empty strings to null and preserves valid times", () => {
      const input = {
        wake_time: "08:00",
        sleep_time: "",
        lunch_time: "  ",
        dinner_time: "19:00"
      };

      const result = cleanHabits(input);

      expect(result).toEqual({
        wake_time: "08:00",
        sleep_time: null,
        lunch_time: null,
        dinner_time: "19:00"
      });
    });

    test("returns undefined if all values become null", () => {
      const input = {
        wake_time: "",
        sleep_time: "   "
      };

      const result = cleanHabits(input);
      expect(result).toBeUndefined();
    });
  });
});
