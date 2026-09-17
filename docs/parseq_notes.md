# PARSeq 최소 동작 확인

[spec.md](spec.md) 의 1차 단계(§4.1 pretrained baseline)를 **가장 작게** 잘라낸 것.
목적은 딱 하나 — **이미지 한 장을 넣었을 때 텍스트가 읽히는가.**

정확도 집계, deskew 전처리, 2개 시리얼 비교 판정은 여기 없다. 이게 돌아가는 걸 확인한 뒤에 붙인다.

## 구성

| 파일 | 역할 |
|---|---|
| `app.py` + `static/index.html` | **브라우저에서 업로드해서 읽기** (제일 편한 확인 방법) |
| `run_ocr.py` | 같은 걸 CLI로. 폴더 일괄 처리, latency 측정 |
| `ocr_core.py` | 모델 로드/전처리/추론 — 웹과 CLI가 공유 |
| `make_sample.py` | 실사진 없을 때 쓸 합성 테스트 이미지 생성 |
| `requirements.txt` | 추론 최소 의존성 |
| `images/` | CLI로 일괄 처리할 크롭 이미지를 넣는 곳 |

## 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 1) torch는 CUDA 버전에 맞춰 먼저 (RTX 4070 Ti Super / 드라이버에 맞는 타겟 선택)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# 2) 나머지
pip install -r requirements.txt
```

CPU만 있어도 동작은 확인된다 (`--device cpu`, 속도만 느림).

## 실행 1 — 웹 페이지 (권장)

```powershell
python app.py
```

뜨는 주소(<http://127.0.0.1:5000>)를 브라우저로 열면 된다. 이미지를 **끌어다 놓거나, 클릭해서 고르거나,
`Ctrl+V` 로 붙여넣으면** 바로 읽는다. 여러 장 한꺼번에 올려도 된다.

- 모델은 서버 뜰 때 한 번만 로드하고 계속 재사용한다 (요청마다 다시 안 올린다)
- 결과 카드에 인식 문자열 · confidence 막대 · 소요 ms · 문자별 confidence가 같이 나온다
- 옵션: `python app.py --model parseq_tiny --device cpu --port 8000`
- 기본은 `127.0.0.1` 바인딩이라 본인 PC에서만 열린다. 같은 망의 다른 PC에서 볼 거면 `--host 0.0.0.0`
  (Flask 개발 서버라 내부망 확인용까지만 쓸 것)

## 실행 2 — CLI

```powershell
# 테스트 이미지 생성 (실사진 있으면 건너뛰고 images/ 에 넣으면 됨)
python make_sample.py

# 읽기
python run_ocr.py

# 특정 파일 / 다른 모델 / latency 측정
python run_ocr.py images/sample_01.png
python run_ocr.py images/sample_01.png --model parseq_tiny
python run_ocr.py images/sample_01.png --bench
```

첫 실행은 `torch.hub` 가 repo와 체크포인트(~90MB)를 `~/.cache/torch/hub` 로 내려받느라 시간이 걸린다.
웹이든 CLI든 마찬가지고, 두 번째부터는 캐시를 쓰므로 오프라인에서도 돈다.

### CLI 출력 예시

```
====================================================================
torch 2.4.0+cu121
model: parseq (pretrained, torch.hub baudm/parseq)
====================================================================
모델 로드 중... (첫 실행은 다운로드 때문에 몇 분 걸릴 수 있다)
  device: cuda (NVIDIA GeForce RTX 4070 Ti SUPER)
  입력 크기(hparams.img_size): (32, 128)

file                           prediction                  conf  min_ch       ms
--------------------------------------------------------------------
sample_01.png                  huts6b906                  0.981   0.988      6.2
```

`conf` 는 문자별 확률의 곱(문자열 전체 신뢰도), `min_ch` 는 가장 약한 문자 하나의 확률이다.
어느 글자에서 흔들리는지 보려면 `--chars` 를 붙이면 문자별로 찍힌다.

## 미리 알아둘 것

- **출력은 소문자로 나온다.** 공식 pretrained PARSeq의 기본 charset은 `0-9a-z` 36자다.
  대소문자 구분이 필요 없다면 비교 시 `.lower()` 로 맞추면 되고, 필요하다면 spec.md §4.2(charset 제한)
  또는 §4.3(파인튜닝)으로 가야 한다.
- **공백과 특수문자(`*` 등)는 baseline이 못 낸다.** `sample_03.png`(`HUTS 6B906 N5 105`)를 일부러
  넣어둔 이유다 — 공백이 사라진 채로 붙어 나올 것이다. spec.md §7의 커스텀 charset 리스크가
  실제로 어떻게 드러나는지 여기서 바로 보인다.
- **합성 샘플 결과로 성능을 판단하면 안 된다.** 조명/각도/인쇄 편차가 전혀 없는 깨끗한 이미지다.
  실측은 spec.md §3.1의 실제 택 크롭으로 해야 한다.

## 문제가 생기면

| 증상 | 대응 |
|---|---|
| `ImportError: cannot import name ... from 'timm.models.helpers'` | timm이 1.x다. `pip install "timm>=0.9,<1.0"` |
| `strhub 전처리 임포트 실패` 메시지 | `pip install lmdb`. 안 깔아도 동등한 fallback 전처리로 그대로 돌아간다 |
| torch.hub 다운로드 실패 | 사내망/프록시 확인. 또는 repo를 직접 clone 후 `torch.hub.load('<로컬경로>', ..., source='local')` |
| CUDA out of memory / cuda 인식 안 됨 | `--device cpu` 로 먼저 동작만 확인 |
| `ModuleNotFoundError: flask` | `pip install flask` (웹 페이지에만 필요) |
| 포트 5000 이미 사용 중 | `python app.py --port 8000` |
| 웹에서 결과가 안 뜬다 | `app.py` 를 띄운 콘솔에 에러가 찍힌다. 브라우저 개발자도구 Network 탭의 `/api/ocr` 응답도 같이 확인 |

## 다음 단계 (spec.md 연결)

1. 실제 택 크롭 수십~100장 확보 → `images/` 에 투입, ground truth 매핑 (§3.2)
2. Exact Match / CER 집계 스크립트 추가 (§5)
3. `cv2.minAreaRect` + `warpAffine` deskew 전처리 삽입 (§3.3)
4. 두 크롭 비교 판정 로직 — 위 결과가 `label_a.lower() == label_b.lower()` 로 충분한지 확인 (§5)
5. 정확도 부족 시 charset 제한 → 파인튜닝 (§4.2, §4.3)
