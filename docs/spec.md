# PARSeq 기반 택 시리얼 번호 OCR 검증 — 테스트 개발 명세서

## 1. 목적 및 범위

**목적**: PARSeq를 이용해 의류 택(포장지/제품)에 부착된 짧은 영숫자 시리얼 번호를 인식하고,
두 크롭 이미지에서 뽑은 시리얼이 서로 일치하는지 판정하는 파이프라인의 실현 가능성을 검증한다.

**이번 단계 범위**: PARSeq 단일 모델 기준 정확도·속도 실측까지. PP-OCRv6 등 타 모델과의 비교,
앙상블 구성은 이번 결과를 보고 후속 단계에서 결정한다.

**성공 기준 (TBD)**: 목표 정확도(Exact Match)와 Task당 허용 latency는 컨베이어벨트 물리적 속도에
맞춰 별도로 확정 필요. 우선은 정확도 최대화를 기준으로 진행하고, 이번 문서의 §5 측정값을 바탕으로
사후에 임계치를 정한다.

---

## 2. 하드웨어 및 환경

| 항목 | 내용 |
|---|---|
| GPU | RTX 4070 Ti Super (16GB VRAM) |
| OS | TBD — 설치 가이드는 Linux/Windows 확정 후 보완 |
| Python | 3.9 이상 (PARSeq repo 요구사항) |
| PyTorch | 2.0 이상, CUDA 11.8+ 또는 12.x (드라이버 버전에 맞춰 설치) |
| 참고 repo | `baudm/parseq` (GitHub, Apache-2.0) |

**설치 개요**
```bash
git clone https://github.com/baudm/parseq.git
cd parseq
make torch-cu121   # 또는 환경에 맞는 CUDA 버전 타겟
pip install -r requirements.txt  # train/test 의존성 포함
```

---

## 3. 데이터 준비

### 3.1 소스
- 실제 택 사진에서 크롭한 이미지 사용. Segmentation 결과 crop을 그대로 쓰는 게 최종 목표이나,
  이번 1차 테스트에서는 수동 크롭도 허용.
- 수량: 정확도 실측용 우선 수십~100장 확보 → 파인튜닝 진행 시 수백 장 이상으로 확대.
- 다양성 확보 항목:
  - 조명 조건 (실제 배치될 암전 터널 + 조명 환경 재현)
  - 각도/기울기 (Segmentation이 보정 못하고 남기는 잔여 오차 범위 포함)
  - 서로 다른 브랜드/폰트 (HAZZYS 외 다른 택 폰트가 섞여 있다면 전부 포함)
  - 인쇄 품질 편차 (흐림, 잉크 번짐, 눌린 자국 등)

### 3.2 라벨링 포맷
- 크롭 이미지 파일명 또는 별도 CSV/JSON에 ground truth 문자열 매핑.
  - 예: `data/images/0001.jpg` ↔ `HUTS 6B906 N5 105`
- 실제 나타나는 전체 문자 집합을 사전에 목록화 (charset 제한에 사용):
  - 대문자 A–Z, 숫자 0–9, 공백, `*` 등. 브랜드별로 특수문자가 다를 수 있으니 전수 확인 필요.

### 3.3 전처리 파이프라인 (Segmentation → OCR 사이)
1. Crop 영역의 최소외접사각형(`cv2.minAreaRect`) 각도 추출 → `warpAffine`으로 수평 정렬.
2. PARSeq 입력 규격에 맞춘 리사이즈 (기본 3×32×128 계열 — 정확한 값은 로드한 체크포인트의
   `hparams.img_size` 확인). 종횡비 유지 padding 방식은 실험으로 결정.
3. 정규화는 PARSeq 공식 전처리(`SceneTextDataModule.get_transform`) 그대로 사용 권장 —
   직접 구현하면 학습/추론 간 불일치로 정확도가 떨어질 수 있음.

---

## 4. 모델 설정 및 테스트 단계

### 4.1 1차: Pretrained 그대로 (Baseline)
- 모델: `parseq` (torch.hub 공식 pretrained, base 버전)
- 목적: 파인튜닝 없이 순정 성능이 이 라벨 폰트에 어느 정도 통하는지 확인.
- 참고 비교군: `parseq_tiny`도 같이 측정 (속도 이득 대비 정확도 손실 확인용 — 이번 태스크는
  속도 여유가 크므로 참고 지표로만 사용).

```python
import torch
from PIL import Image
from strhub.data.module import SceneTextDataModule

parseq = torch.hub.load('baudm/parseq', 'parseq', pretrained=True).eval().cuda()
img_transform = SceneTextDataModule.get_transform(parseq.hparams.img_size)

img = Image.open('crop.jpg').convert('RGB')
img = img_transform(img).unsqueeze(0).cuda()

logits = parseq(img)
pred = logits.softmax(-1)
label, confidence = parseq.tokenizer.decode(pred)
print(label[0], confidence[0])
```

### 4.2 2차: Charset 제한
- 디코더 문자 집합을 실사용 문자(영문 대문자+숫자+공백+특수문자)로 제한.
- 공식 repo의 `--cased`/`--punctuation` 옵션은 사전 정의된 문자 집합만 지원하므로,
  브랜드마다 다른 특수문자가 있다면 커스텀 charset 학습이 필요할 수 있음 (repo Issue #5, #9
  참고 — 이번 니즈에 충분한지 확인 필요, §7 리스크 항목 참조).

### 4.3 3차: 파인튜닝
- §3.1에서 모은 실 데이터로 fine-tuning.
- Train/Val/Test 분할: 우선 70/15/15 (데이터 양 확보되는 대로 조정).
- Augmentation: 회전(실측 잔여 오차 범위), 밝기/대비 변화, 경미한 blur — 실제 조명·각도
  변주 계획(§물리 테스트)과 맞춰서 구성.
- 학습 설정(epoch, learning rate 등)은 repo 기본 config로 시작 후, 1차 결과 보고 조정.

---

## 5. 평가 지표 및 측정 방법론

**정확도**
- 주 지표: 문자열 완전일치율 (Exact Match Accuracy) — 이 태스크의 핵심 지표.
- 보조 지표: 문자 단위 오류율(CER) — 어느 위치에서 주로 틀리는지 진단용.

**속도**
- GPU에서 이미지 1장당 추론 latency(ms), 배치 크기 1 기준.
- Task 정의상 2회 인식 합산 시간도 별도로 기록.
- 측정 절차:
  1. warm-up 10회 이상 실행 후 측정 시작 (콜드 스타트 제외).
  2. 최소 100회 반복, 평균·중앙값·95th percentile 모두 기록 (평균만 보면 이상치에 왜곡됨).
  3. `torch.cuda.synchronize()` 호출 후 시간 측정 (비동기 실행으로 인한 측정 오류 방지).

**판정 로직 검증**
- 두 크롭(예: 포장지 vs 제품 시리얼)이 완전일치하는 케이스 / 의도적으로 불일치시킨 케이스를
  각각 샘플로 준비해서, 최종 판정 로직(exact match, 필요시 문자 단위 confidence 기반 완화)의
  정탐률·오탐률도 함께 확인.

---

## 6. 산출물 (Deliverables)

- [ ] 환경 세팅 스크립트/문서 (requirements, 설치 가이드)
- [ ] 전처리(deskew, resize) 모듈
- [ ] 추론 + latency 측정 스크립트
- [ ] Baseline(pretrained) 결과 리포트 — 정확도/속도
- [ ] Charset 제한 적용 결과 리포트
- [ ] (데이터 확보 시) 파인튜닝 결과 리포트
- [ ] 2개 시리얼 비교 판정 로직 프로토타입

---

## 7. 리스크 / 확인 필요 사항

- PARSeq 공식 repo의 커스텀 charset 학습 지원 범위가 실제 브랜드별 특수문자 케이스를
  다 커버하는지 (repo Issue #5, #9에 방법이 언급되나 실사용 검증 필요).
- 이번 테스트 데이터가 실제 배치 환경(조명, crop 정확도, 컨베이어 진동 등)을 얼마나
  반영하는지 — 초기 샘플만으로 성능을 과신하지 않도록 지속 점검.
- 파인튜닝용 데이터 수집 물량 확보 일정.
- 목표 정확도·Task당 허용 latency의 구체적 수치가 아직 미정 — 컨베이어벨트 사양 확정 후 보완.

---

## 8. 다음 단계

- 1차 테스트(순정 pretrained) 결과가 나오면, 그 수치를 기준으로 PP-OCRv6 recognition과의
  비교 진행 여부를 결정한다.
- 정확도가 목표 임계치(추후 확정)에 못 미치면 파인튜닝으로 바로 이행한다.