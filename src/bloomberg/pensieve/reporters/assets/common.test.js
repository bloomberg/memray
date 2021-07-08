import { humanFileSize, makeTooltipString, filterChildThreads } from "./common";

test("handlesSmallValues", () => {
  expect(humanFileSize(0)).toBe("0 B");
  expect(humanFileSize(128)).toBe("128 B");
  expect(humanFileSize(1023)).toBe("1023 B");
});

describe("Flame graph tooltip generation", () => {
  test("Generate label without thread", () => {
    const data = {
      location: "File foo.py, line 10 in foo",
      allocations_label: "3 allocations",
      thread_id: -1,
    };
    expect(makeTooltipString(data, "1KiB", true)).toBe(
      "File foo.py, line 10 in foo<br>1KiB total<br>3 allocations"
    );
  });

  test("Generate label with thread", () => {
    const data = {
      location: "File foo.py, line 10 in foo",
      allocations_label: "3 allocations",
      thread_id: 1,
    };
    expect(makeTooltipString(data, "1KiB", false)).toBe(
      "File foo.py, line 10 in foo<br>1KiB total<br>3 allocations<br>Thread ID: 1"
    );
  });
});

describe("Filter threads", () => {
  const data = {
    thread_id: 0,
    children: [
      {
        thread_id: 1,
        children: [
          {
            thread_id: 1,
            children: [
              {
                thread_id: 1,
                children: [],
              },
            ],
          },
        ],
      },
      {
        thread_id: 2,
        children: [],
      },
    ],
  };

  test("Filter a single thread", () => {
    const result = filterChildThreads(data, 1);
    expect(result).toStrictEqual({
      thread_id: 0,
      children: [
        {
          thread_id: 1,
          children: [
            {
              thread_id: 1,
              children: [
                {
                  thread_id: 1,
                  children: [],
                },
              ],
            },
          ],
        },
      ],
    });
  });
  test("Filter multiple threads", () => {
    const result = filterChildThreads(data, 2);
    expect(result).toStrictEqual({
      thread_id: 0,
      children: [
        {
          thread_id: 2,
          children: [],
        },
      ],
    });
  });
  test("Filter empty children", () => {
    expect(
      filterChildThreads(
        {
          thread_id: 0,
          children: [],
        },
        2
      )
    ).toStrictEqual({
      thread_id: 0,
      children: [],
    });
  });
});
