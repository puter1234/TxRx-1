import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, CreditCard, ScanText, Settings } from "lucide-react";
import { api } from "../station/shared";
import { useApp } from "../lib/store";
import { ended, reportError } from "../lib/station";
import Help from "../components/Help";
import { Equipment as EquipmentDetails } from "../station/StationApp";
import { BenchHeader, CameraTest, OutputTests, SensorTest, useBench } from "../components/DeviceTests";

export default function Equipment() {
  const nav = useNavigate(), bench = useBench();
  const state = useApp(s => s.snapshot), online = useApp(s => s.connected);
  const [ocr, setOcr] = useState<{ok: boolean; detail: string} | null>(null);
  const locked = !online || !ended(state?.session) || bench.busy || !!bench.state?.native_busy || !!bench.state?.run;
  const rfid = bench.state?.rfid;
  return <div className="flex h-full flex-col">
    <div className="flex shrink-0 items-center gap-4 px-6 pt-5">
      <button className="btn btn-outline btn-sm" onClick={() => nav("/")}><ArrowLeft size={20}/>처음 화면</button>
      <h1 className="text-2xl font-extrabold">장비 점검</h1>
      <button className="btn btn-outline ml-auto" onClick={() => nav("/settings?tab=devices")}><Settings size={22}/>연결 설정</button>
    </div>
    <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-6">
      <BenchHeader bench={bench}/>
      <div className="grid gap-5 md:grid-cols-2"><OutputTests bench={bench}/></div>
      <SensorTest bench={bench}/>
      <CameraTest bench={bench}/>
      <div className="grid gap-5 md:grid-cols-2">
        <section className="card space-y-4 p-5">
          <div className="flex items-center gap-3"><CreditCard size={26}/><h2 className="text-xl font-extrabold">RFID 확인</h2>
            <Help text="설정한 직렬 포트에서 실제 태그를 읽습니다. EPC와 읽은 횟수를 표시하며 생산 수량에는 반영하지 않습니다."/></div>
          <button className="btn btn-primary w-full" disabled={locked} onClick={() => bench.action(() => api("/bench/rfid", {}))}>태그 읽기</button>
          {rfid ? <div className="space-y-3"><p className="text-xl font-bold">{rfid.detail}</p>
            {rfid.tags.map((tag: any) => <div key={tag.epc} className="space-y-2 rounded-xl bg-panel p-4">
              <p className="break-all font-mono text-xl font-bold">{tag.epc}</p>
              <p className="text-lg font-bold">읽은 횟수 {tag.count}회</p>
              <p className="text-lg">최대 RSSI {tag.max_rssi}, 중앙 RSSI {tag.median_rssi}</p>
            </div>)}
          </div> : <p className="text-lg font-bold">읽은 태그 없음</p>}
        </section>
        <section className="card space-y-4 p-5">
          <div className="flex items-center gap-3"><ScanText size={26}/><h2 className="text-xl font-extrabold">OCR 인식 확인</h2>
            <Help text="문자 인식 모델이 이 컴퓨터에서 열리는지 확인합니다. 카메라 영상 확인과 사진 촬영은 위 카메라 항목에서 시험합니다."/></div>
          <button className="btn btn-outline w-full" disabled={locked} onClick={() => bench.action(async () => setOcr(await api("/bench/ocr", {})))}>모델 확인</button>
          {ocr && <p role="status" className={"text-lg font-bold " + (ocr.ok ? "text-ok" : "text-danger")}>{ocr.detail}</p>}
        </section>
      </div>
      <details className="card p-5">
        <summary className="cursor-pointer text-xl font-bold">상세 장비 정보</summary>
        <div className="mt-5"><EquipmentDetails action={async fn => { try { await fn(); } catch(e) { reportError(e); } }} role="operator"/></div>
      </details>
    </div>
  </div>;
}
