import { useEffect, useState } from "react";
import { api, Field } from "./shared";
import type { Action } from "./shared";
type User = { username: string; role: string; enabled: boolean };
const blank = {
  username: "",
  role: "operator",
  enabled: true,
  password: "",
  reason: "",
};
export default function Users({
  action,
  locked,
}: {
  action: Action;
  locked: boolean;
}) {
  const [users, setUsers] = useState<User[]>([]),
    [draft, setDraft] = useState(blank),
    [error, setError] = useState("");
  const refresh = () => api<User[]>("/users").then(setUsers);
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, []);
  return (
    <div className="card space-y-5 p-6">
      <h2 className="text-2xl font-extrabold">사용자·권한 관리</h2>
      <p>
        작업자는 운전·조회, 엔지니어는 복구·수량 보정·OCR 영역 설정, 관리자는
        기준 데이터·계정 관리가 가능합니다.
      </p>
      {error && <p role="alert">{error}</p>}
      {locked && (
        <p className="text-danger">
          진행 중인 작업을 종료한 후 계정을 변경하세요.
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        {users.map((u) => (
          <button
            className="btn btn-outline"
            key={u.username}
            onClick={() => setDraft({ ...u, password: "", reason: "" })}
          >
            {u.username} · {u.role} · {u.enabled ? "활성" : "중지"}
          </button>
        ))}
        <button className="btn btn-outline" onClick={() => setDraft(blank)}>
          사용자 추가
        </button>
      </div>
      <Field label="사용자 ID">
        <input
          className="field"
          value={draft.username}
          onChange={(e) => setDraft({ ...draft, username: e.target.value })}
        />
      </Field>
      <Field label="권한">
        <select
          className="field"
          value={draft.role}
          onChange={(e) => setDraft({ ...draft, role: e.target.value })}
        >
          <option value="operator">작업자</option>
          <option value="engineer">엔지니어</option>
          <option value="admin">관리자</option>
        </select>
      </Field>
      <Field label="새 비밀번호 (기존 계정은 비워 두면 유지)">
        <input
          type="password"
          autoComplete="new-password"
          className="field"
          value={draft.password}
          onChange={(e) => setDraft({ ...draft, password: e.target.value })}
        />
      </Field>
      <label className="flex gap-3">
        <input
          type="checkbox"
          checked={draft.enabled}
          onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
        />
        계정 활성
      </label>
      <Field label="계정 변경 사유">
        <input
          className="field"
          value={draft.reason}
          onChange={(e) => setDraft({ ...draft, reason: e.target.value })}
        />
      </Field>
      <button
        className="btn btn-primary"
        disabled={locked || !draft.username || draft.reason.trim().length < 3}
        onClick={() =>
          action(async () => {
            await api("/users", draft);
            setDraft(blank);
            await refresh();
          }, "사용자 설정과 감사 이력을 저장했습니다. 변경한 계정은 다시 로그인해야 합니다.")
        }
      >
        사용자 설정 저장
      </button>
    </div>
  );
}
