import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Config from "./Config";
import Work from "./Work";
import type { Brand, Snapshot, Action } from "./shared";

const brand: Brand = {
  id: "hazzys",
  name: "헤지스",
  revision: 1,
  options: [
    { key: "style", label: "품번", values: ["HUTS6C612"] },
    { key: "color", label: "색상", values: ["N3", "BK"] },
    { key: "size", label: "사이즈", values: ["095", "100"] },
  ],
  decoder: { kind: "hazzys_6bit_crc8", records: {} },
  ocr_regions: [],
  barcode_records: {},
  note: "",
};
const snapshot: Snapshot = {
  boot_id: "boot",
  revision: 1,
  mode: "REPLAY",
  session: null,
  busy: false,
  last_result: null,
  stop_fault: null,
  io: {},
  vision: {
    loaded: false,
    local_assets_present: true,
    error: null,
    busy: false,
  },
};
const action: Action = async (fn) => {
  await fn();
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("operator flows without browser or screenshots", () => {
  it("uses server readiness and denies recovery to the operator role", () => {
    const state: Snapshot = {
      ...snapshot,
      can_start: false,
      blockers: ["센서 실측 필요"],
      session: {
        id: "s1",
        phase: "READY",
        count: 0,
        passed: 0,
        failed: 0,
        adjustments: 0,
        created_at: "2026-09-17",
        active_product: null,
        recipe: {
          brand_id: "hazzys",
          brand_revision: 1,
          targets: { size: "095" },
          channels: ["rfid"],
          target_count: null,
        },
        brand,
        fault: null,
        mode: "REPLAY",
      },
    };
    render(
      <Work
        state={state}
        brands={[brand]}
        action={action}
        refresh={async () => {}}
        online
        role="operator"
      />,
    );
    expect(
      (screen.getByRole("button", { name: "운전 준비" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByText("운전 준비 조건: 센서 실측 필요")).toBeTruthy();
    expect(
      (
        screen.getByRole("button", {
          name: "수량 수동 보정",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: "정지 요청" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("keeps STOP usable while a start request awaits a response", async () => {
    const user = userEvent.setup();
    let finish: (value: unknown) => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      ),
    );
    const state: Snapshot = {
      ...snapshot,
      can_start: true,
      session: {
        id: "s1",
        phase: "READY",
        count: 0,
        passed: 0,
        failed: 0,
        adjustments: 0,
        created_at: "2026-09-17",
        active_product: null,
        recipe: {
          brand_id: "hazzys",
          brand_revision: 1,
          targets: { size: "095" },
          channels: ["rfid"],
          target_count: null,
        },
        brand,
        fault: null,
        mode: "REPLAY",
      },
    };
    render(
      <Work
        state={state}
        brands={[brand]}
        action={action}
        refresh={async () => {}}
        online
      />,
    );
    await user.click(screen.getByRole("button", { name: "운전 준비" }));
    expect(
      (screen.getByRole("button", { name: "운전 준비" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: "정지 요청" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
    finish({ ok: true, json: async () => ({}) });
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "운전 준비" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    );
  });

  it("selects one target per editable option and barcode stays optional", async () => {
    const user = userEvent.setup();
    const fetcher = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetcher);
    render(
      <Work
        state={snapshot}
        brands={[brand]}
        action={action}
        refresh={async () => {}}
        online
      />,
    );
    const create = screen.getByRole("button", {
      name: "선택한 목표로 작업 생성",
    }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);
    await user.selectOptions(screen.getByLabelText("메이커"), "hazzys");
    await user.selectOptions(screen.getByLabelText("품번"), "HUTS6C612");
    await user.selectOptions(screen.getByLabelText("색상"), "N3");
    await user.selectOptions(screen.getByLabelText("사이즈"), "095");
    expect(
      (screen.getByLabelText("바코드 (선택)") as HTMLInputElement).checked,
    ).toBe(false);
    await user.click(screen.getByLabelText("OCR 문자"));
    await user.click(create);
    const body = JSON.parse(fetcher.mock.calls[0][1].body);
    expect(body.targets).toEqual({
      style: "HUTS6C612",
      color: "N3",
      size: "095",
    });
    expect(body.channels).toEqual(["rfid"]);
  });

  it("supports option addition and deletion from settings", async () => {
    const user = userEvent.setup();
    render(
      <Config
        brands={[brand]}
        action={action}
        refresh={async () => {}}
        locked={false}
      />,
    );
    await user.click(screen.getByRole("button", { name: "헤지스" }));
    await user.type(screen.getByLabelText("새 옵션 키"), "season");
    await user.type(screen.getByLabelText("새 옵션 이름"), "시즌");
    await user.click(screen.getByRole("button", { name: "옵션 추가" }));
    expect(screen.getByLabelText("시즌 선택값")).toBeTruthy();
    await user.type(screen.getByLabelText("시즌 선택값"), "SS, FW");
    const buttons = screen.getAllByRole("button", { name: "옵션 삭제" });
    await user.click(buttons[3]);
    expect(screen.queryByLabelText("시즌 선택값")).toBeNull();
  });

  it("locks settings while a product job is active", async () => {
    const user = userEvent.setup();
    render(
      <Config
        brands={[brand]}
        action={action}
        refresh={async () => {}}
        locked
      />,
    );
    await user.click(screen.getByRole("button", { name: "헤지스" }));
    expect(
      (screen.getByRole("button", { name: "설정 저장" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("requires an operator reason and does not offer run during a latched failure", async () => {
    const user = userEvent.setup();
    const fetcher = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetcher);
    const state: Snapshot = {
      ...snapshot,
      session: {
        id: "s1",
        phase: "HOLD",
        count: 0,
        passed: 0,
        failed: 1,
        adjustments: 0,
        created_at: "2026-09-17",
        active_product: "p1",
        recipe: {
          brand_id: "hazzys",
          brand_revision: 1,
          targets: { size: "095" },
          channels: ["rfid"],
          target_count: null,
        },
        brand,
        fault: "REQUIRED_FIELD_MISSING",
        mode: "REPLAY",
      },
    };
    render(
      <Work
        state={state}
        brands={[brand]}
        action={action}
        refresh={async () => {}}
        online
      />,
    );
    expect(
      (screen.getByRole("button", { name: "운전 준비" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    const reset = screen.getByRole("button", {
      name: "조치 확인 · 오류 해제",
    }) as HTMLButtonElement;
    expect(reset.disabled).toBe(true);
    await user.type(
      screen.getByLabelText("작업자 조치·보정 사유"),
      "제품 확인 후 재검사",
    );
    await user.click(reset);
    await waitFor(() => expect(fetcher).toHaveBeenCalled());
    expect(JSON.parse(fetcher.mock.calls[0][1].body).action).toBe("reset");
  });
});
