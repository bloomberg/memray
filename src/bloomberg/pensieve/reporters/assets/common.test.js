import { humanFileSize } from "./common";

test("handlesSmallValues", () => {
  expect(humanFileSize(0)).toBe("0 B");
  expect(humanFileSize(128)).toBe("128 B");
  expect(humanFileSize(1023)).toBe("1023 B");
});
