import { humanFileSize, makeTooltipString} from "./common";

test("handlesSmallValues", () => {
  expect(humanFileSize(0)).toBe("0 B");
  expect(humanFileSize(128)).toBe("128 B");
  expect(humanFileSize(1023)).toBe("1023 B");
});

describe("Flame graph tooltip generation", () => {
  test("Generate label without thread", () => {
    const data = {
      "location": "File foo.py, line 10 in foo",
      "allocations_label": "3 allocations",
      "thread_id": -1
    };
    expect(makeTooltipString(data, "1KiB")).toBe("File foo.py, line 10 in foo<br>1KiB total<br>3 allocations")
  });

  test("Generate label with thread", () => {
    const data = {
      "location": "File foo.py, line 10 in foo",
      "allocations_label": "3 allocations",
      "thread_id": 1
    };
    expect(makeTooltipString(data, "1KiB")).toBe("File foo.py, line 10 in foo<br>1KiB total<br>3 allocations<br>Thread ID: 1")
  });
})
