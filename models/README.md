# 로컬 모델

기존 PARSeq 소스와 `parseq-bb5792a6.pt`를 `scripts/prepare_local_assets.py`로 이 디렉터리에 복사한다. 해시 검증 후 `pretrained=False`로 로컬 모델을 생성하고 로컬 state dict만 읽는다. 운영 중 torch.hub 원격 조회·모델 다운로드를 하지 않는다. 소스 라이선스를 복사본에 보존한다. 배포 묶음에는 이 디렉터리를 반드시 포함한다.
