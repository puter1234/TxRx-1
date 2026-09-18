import { afterEach, expect, it, vi } from "vitest";
import { useState } from "react";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import OptionButtons from "../components/OptionButtons";
import Config from "./Config";
import type { Brand, Option } from "./shared";
import { colorInk } from "../lib/optionColors";

const color: Option = {
  key: "color",
  label: "색상",
  values: ["N3", "WH", "BK"],
  colors: { N3: "#142B49", WH: "#FFFFFF" },
};
const brand: Brand = {
  id: "test",
  name: "테스트 브랜드",
  revision: 1,
  options: [color],
  decoder: { kind: "none", records: {} },
  ocr_regions: [],
  barcode_records: {},
  note: "",
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows assigned colors, readable codes and exactly one selected button", async () => {
  const user = userEvent.setup();
  function Example() {
    const [value, setValue] = useState("");
    return <OptionButtons option={color} value={value} onChange={setValue} />;
  }
  render(<Example />);
  const group = within(screen.getByRole("group", { name: "색상" }));
  const navy = group.getByRole("button", { name: "N3" }),
    white = group.getByRole("button", { name: "WH" }),
    unknown = group.getByRole("button", { name: "BK" });
  expect(navy.style.backgroundColor).toBe("rgb(20, 43, 73)");
  expect(navy.style.color).toBe("rgb(255, 255, 255)");
  expect(white.style.color).toBe("rgb(0, 0, 0)");
  expect(unknown.style.backgroundColor).toBe("");
  await user.click(navy);
  expect(navy.getAttribute("aria-pressed")).toBe("true");
  await user.click(white);
  expect(white.getAttribute("aria-pressed")).toBe("true");
  expect(navy.getAttribute("aria-pressed")).toBe("false");
  expect(group.getAllByRole("button", { pressed: true })).toHaveLength(1);
  expect(colorInk("#777777")).toBe("#000000");
});

it("supports size selection by keyboard and searching long option lists", async () => {
  const user = userEvent.setup(),
    selected = vi.fn();
  render(
    <OptionButtons
      option={{ key: "size", label: "사이즈", values: ["095", "100"] }}
      value=""
      onChange={selected}
    />,
  );
  await user.tab();
  await user.keyboard(" ");
  expect(selected).toHaveBeenCalledWith("095");
  cleanup();
  render(
    <OptionButtons
      option={{
        key: "style",
        label: "품번",
        values: Array.from({ length: 20 }, (_, i) => "ITEM" + i),
      }}
      value=""
      onChange={selected}
    />,
  );
  await user.type(screen.getByLabelText("품번 검색"), "ITEM19");
  expect(screen.getAllByRole("button")).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "ITEM19" }));
  expect(selected).toHaveBeenLastCalledWith("ITEM19");
});

it("assigns a code color in settings and persists its exact code separately from the display color", async () => {
  const user = userEvent.setup();
  const fetcher = vi.fn(async (_path: string, args: RequestInit) => ({
    ok: true,
    json: async () => ({
      ...JSON.parse(args.body as string).brand,
      revision: 2,
    }),
  }));
  vi.stubGlobal("fetch", fetcher);
  render(
    <Config
      brands={[brand]}
      locked={false}
      refresh={async () => {}}
      action={async (fn) => {
        await fn();
      }}
    />,
  );
  await user.click(screen.getByRole("button", { name: "테스트 브랜드" }));
  await user.click(screen.getByRole("button", { name: "BK 색상 지정" }));
  await user.click(screen.getByRole("button", { name: "검정" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(
    screen.getByRole("button", { name: "BK 색상 지정" }).style.backgroundColor,
  ).toBe("rgb(0, 0, 0)");
  await user.type(screen.getByLabelText("설정 변경 사유"), "색상 표시 등록");
  await user.click(screen.getByRole("button", { name: "설정 저장" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
  const saved = JSON.parse(fetcher.mock.calls[0][1].body as string).brand;
  expect(saved.options[0].values).toEqual(["N3", "WH", "BK"]);
  expect(saved.options[0].colors).toEqual({
    N3: "#142B49",
    WH: "#FFFFFF",
    BK: "#000000",
  });
});

it("clears mappings for deleted codes and validates custom color input", async () => {
  const user = userEvent.setup();
  const fetcher = vi.fn(async (_path: string, args: RequestInit) => ({
    ok: true,
    json: async () => JSON.parse(args.body as string).brand,
  }));
  vi.stubGlobal("fetch", fetcher);
  render(
    <Config
      brands={[brand]}
      locked={false}
      refresh={async () => {}}
      action={async (fn) => {
        await fn();
      }}
    />,
  );
  await user.click(screen.getByRole("button", { name: "테스트 브랜드" }));
  await user.click(screen.getByRole("button", { name: "N3 색상 지정" }));
  await user.clear(screen.getByLabelText("색상 값"));
  await user.type(screen.getByLabelText("색상 값"), "invalid");
  expect(
    (screen.getByRole("button", { name: "적용" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  await user.clear(screen.getByLabelText("색상 값"));
  await user.type(screen.getByLabelText("색상 값"), "#Ab1234");
  await user.click(screen.getByRole("button", { name: "적용" }));
  await user.clear(screen.getByLabelText("색상 선택값"));
  await user.type(screen.getByLabelText("색상 선택값"), "N3, BK");
  expect(screen.queryByRole("button", { name: "WH 색상 지정" })).toBeNull();
  await user.type(screen.getByLabelText("설정 변경 사유"), "선택값 수정");
  await user.click(screen.getByRole("button", { name: "설정 저장" }));
  const option = JSON.parse(fetcher.mock.calls[0][1].body as string).brand
    .options[0];
  expect(option.colors.WH).toBeUndefined();
  expect(option.values).toEqual(["N3", "BK"]);
});
