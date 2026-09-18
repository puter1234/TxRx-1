import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Login } from "./StationApp";
import type { Action } from "./shared";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("password-only entry", () => {
  it("enters with the existing password, without an account field or payload", async () => {
    const user = userEvent.setup();
    const entered = vi.fn();
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
    vi.stubGlobal("fetch", fetcher);
    render(<Login configured onLogin={entered} action={async (fn) => { await fn(); }} />);
    expect(screen.queryByLabelText("사용자 ID")).toBeNull();
    await user.type(screen.getByLabelText("비밀번호"), "existing-password{Enter}");
    await waitFor(() => expect(entered).toHaveBeenCalledOnce());
    expect(fetcher.mock.calls[0][0]).toBe("/api/auth/login");
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ password: "existing-password" });
  });

  it("sets only a password on first use, requiring matching confirmation", async () => {
    const user = userEvent.setup();
    const entered = vi.fn();
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
    vi.stubGlobal("fetch", fetcher);
    render(<Login configured={false} onLogin={entered} action={async (fn) => { await fn(); }} />);
    const start = screen.getByRole("button", { name: "설정 후 시작" }) as HTMLButtonElement;
    await user.type(screen.getByLabelText("새 비밀번호 (6자 이상)"), "station-password");
    expect(start.disabled).toBe(true);
    await user.type(screen.getByLabelText("비밀번호 확인"), "station-password");
    await user.click(start);
    await waitFor(() => expect(entered).toHaveBeenCalledOnce());
    expect(fetcher.mock.calls[0][0]).toBe("/api/auth/setup");
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ password: "station-password" });
  });

  it("reports a wrong password without asking for an ID and permits retry", async () => {
    const user = userEvent.setup();
    const entered = vi.fn();
    const errors: string[] = [];
    const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 400, json: async () => ({ detail: "사용자 ID 또는 비밀번호를 확인하세요." }) });
    vi.stubGlobal("fetch", fetcher);
    const action: Action = async (fn) => { try { await fn(); } catch (e) { errors.push((e as Error).message); } };
    render(<Login configured onLogin={entered} action={action} />);
    await user.type(screen.getByLabelText("비밀번호"), "wrong-password{Enter}");
    await waitFor(() => expect(errors).toEqual(["비밀번호를 확인하세요."]));
    expect(entered).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "들어가기" }) as HTMLButtonElement).disabled).toBe(false);
  });
});
