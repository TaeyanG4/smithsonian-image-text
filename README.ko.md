# Smithsonian 25K 박물관 이미지-텍스트 데이터셋

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md)

[![CI](https://github.com/TaeyanG4/smithsonian-image-text/actions/workflows/ci.yml/badge.svg)](https://github.com/TaeyanG4/smithsonian-image-text/actions/workflows/ci.yml)

Smithsonian Open Access 자료를 권리 검증 후 이미지-텍스트 데이터셋으로 구축하고 Kaggle에 배포하기 위한 재현 가능한 도구 모음입니다.

**Kaggle:** [Smithsonian 25K Museum Image-Text Dataset](https://www.kaggle.com/datasets/taeyangg4/smithsonian-25k-museum-image-text)

**현재 공개 릴리스:** CC0 이미지 24,972장, 풍부한 메타데이터, 누수 방지 분할, 균형 잡힌 5K 스타터 세트.

## 현재 릴리스

Dataset Version 3가 현재 Kaggle 공개 릴리스입니다. 검증된 이미지 행과 canonical metadata는 그대로 유지하면서 Kaggle 파일 구조만 정리해, 사용자가 핵심 테이블과 문서를 빠르게 찾을 수 있도록 했습니다.

- 공개 JPEG 이미지 **24,972장**.
- 4,621개 객체에서 구성한 균형 잡힌 **5,000행** 스타터 서브셋.
- **train 19,979 / validation 2,498 / test 2,495**행, `object_id` 중복 0건.
- canonical `metadata.parquet`의 **43/43** 컬럼에 Data Explorer 설명 등록.
- Kaggle Data Explorer 루트는 의도적으로 `README.md` + `metadata.parquet`만 유지.
- 현재 Kaggle Usability 점수: **10.00 / 10**.
- 최종 검증 릴리스 크기는 약 **1.03 GB**로 5 GB 하드캡보다 충분히 작습니다.

## 릴리스 원칙

- Smithsonian 공식 메타데이터를 source of truth로 사용합니다.
- 레코드 메타데이터와 실제로 선택된 이미지 미디어 항목 모두 `CC0`를 명시해야 합니다.
- 공식 Smithsonian IDS 파생 이미지를 우선하며 목표 최대 변 길이는 512 px입니다.
- 하나의 `object_id`는 train/validation/test 중 정확히 한 split에만 포함됩니다.
- 정확히 25,000행을 채우는 것보다 품질을 우선합니다.
- 민감하거나 모호한 자료는 자동 공개하지 않고 검토 대상으로 격리합니다.
- 3D, 오디오, 비디오, 대규모 OCR/문서 코퍼스, 자유형 LLM 캡션은 기본 데이터셋에서 제외합니다.

## 빌드 요약

- 탐색 단계에서 미디어 단위 CC0 후보 **97,718건**을 수집했습니다.
- 적격성 필터링 결과는 **적격 90,451 / 검토 필요 639 / 거절 6,628**입니다.
- 이미지 다운로드 전 균형 선택 단계에서 **18,321개 객체**로부터 정확히 **25,000행**을 선택했습니다.
- 필수 1K 파일럿은 HTTP/디코드 **1,000 / 1,000 성공**으로 패키지 크기 게이트를 통과했습니다.
- 운영 수집에서는 **24,972장**을 유지했습니다. 재시도 후에도 25개 원본 파생 이미지가 HTTP 404였고 3개는 최소 256 px 미만이어서 해당 행을 억지로 보충하지 않았습니다.
- QA에서 모든 JPEG를 다시 디코딩했고 SHA256 완전 중복 0건, 반복 `media_id` 그룹 0건을 확인했습니다.
- 모델용 텍스트는 Smithsonian 필드만으로 구성하며 전체 보존 행에서 100% 비어 있지 않고 최대 512자로 제한됩니다. 원본 `description`은 그대로 유지합니다.
- 최종 검증에서 이미지, 권리, 치수, split 누수, checksum 게이트를 모두 통과했습니다.
- CLIP ViT-B/32 임베딩은 선택적 side artifact이며 기본 릴리스에는 포함하지 않습니다.

## 권리 게이트

레코드 수준의 메타데이터 라이선스만 보고 이미지 권리를 추정하지 않습니다. 레코드 메타데이터는 CC0여도 첨부 이미지에는 별도 사용 제한이 있을 수 있습니다. 자동 적격성 판정은 아래 세 조건을 모두 요구합니다.

1. `content.descriptiveNonRepeating.metadata_usage.access == "CC0"`
2. media `type == "Images"`
3. 선택된 바로 그 media item의 `usage.access == "CC0"`

그 외 항목은 정책 설정에 따라 거절하거나 검토 대상으로 보냅니다.

## 파이프라인

수집 흐름은 권리, 품질, split 게이트를 다음 순서로 보존합니다.

```text
discover_metadata.py -> build_candidate_tables.py -> select_candidates.py
-> run_pilot.py -> download_images.py -> qa_images.py
-> build_metadata.py -> create_splits.py -> build_starter.py
-> build_release.py -> validate_release.py
```

대규모 Phase 2 수집은 항상 명시적으로 실행합니다. `data/` 아래의 대용량 산출물은 Git에서 제외됩니다.

## 개발 환경

Python 3.11 이상을 지원합니다.

```powershell
python -m pip install -e ".[data,dev]"
python -m pytest -q
python -m ruff check .
```

CI matrix는 Python 3.11과 3.12에서 동일한 테스트를 실행합니다.

## 안전한 메타데이터 스모크 테스트

이 명령은 Smithsonian **메타데이터 shard만** 내려받아 작은 대표 unit 집합에서 최대 250개의 CC0 이미지-미디어 후보를 생성합니다. 컬렉션 이미지는 다운로드하지 않습니다.

```powershell
python scripts/discover_metadata.py
```

전체 재빌드는 명시적인 output/report 경로와 `--all-preferred-units --target ...`를 사용합니다. CLI가 스모크 테스트 기본값을 자동으로 대규모 크롤링으로 바꾸지 않습니다.

## Smithsonian API 키

bulk metadata 원본은 공개되어 있어 API 키가 필요하지 않습니다. Smithsonian API를 사용하는 스크립트에서는 자신의 data.gov 키를 환경 변수로 제공하고 Git에는 커밋하지 마세요.

```powershell
$env:SMITHSONIAN_API_KEY = "..."
python scripts/probe_sources.py
```

## 저장소 구조

```text
config/                     수집 및 적격성 정책
docs/                       출처, 권리, 스키마, 탐색, Kaggle 배포 문서
src/smithsonian_image_text/ 메타데이터, 필터링, 이미지, 텍스트, split 로직
scripts/                    탐색부터 릴리스/검증까지의 실행 진입점
tests/                      네트워크 비사용 단위 테스트
data/                       로컬 빌드 산출물; 대용량 파일은 gitignore 처리
```

## 문서

- `docs/SOURCES.md`
- `docs/RIGHTS_POLICY.md`
- `docs/SCHEMA_RESEARCH.md`
- `docs/DISCOVERY_STRATEGY.md`
- `docs/DISTRIBUTION.md`
- `docs/KAGGLE_PUBLISHING.md`

기계 판독용 제어 설정은 `config/collection.yaml`과 `config/eligibility_rules.yaml`에 있습니다.
