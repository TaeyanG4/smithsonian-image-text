# Smithsonian 25K 博物館画像・テキストデータセット

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md)

[![CI](https://github.com/TaeyanG4/smithsonian-image-text/actions/workflows/ci.yml/badge.svg)](https://github.com/TaeyanG4/smithsonian-image-text/actions/workflows/ci.yml)

Smithsonian Open Access の資料を権利監査したうえで画像・テキストデータセットとして構築し、Kaggle に公開するための再現可能なツール群です。

**Kaggle:** [Smithsonian 25K Museum Image-Text Dataset](https://www.kaggle.com/datasets/taeyangg4/smithsonian-25k-museum-image-text)

**現在の公開リリース:** CC0 画像 24,972 枚、豊富なメタデータ、リークを防ぐ分割、バランスされた 5K スターターセット。

## 現在のリリース

Dataset Version 3 が現在の Kaggle 公開リリースです。検証済みの画像行と canonical metadata は変更せず、Kaggle 上のファイル構成だけを整理し、主要テーブルとドキュメントを見つけやすくしています。

- 公開 JPEG 画像 **24,972 枚**。
- 4,621 オブジェクトから構成したバランス済み **5,000 行**スターターサブセット。
- **train 19,979 / validation 2,498 / test 2,495** 行、`object_id` の重複は 0。
- canonical `metadata.parquet` の **43/43** 列に Data Explorer の説明を登録済み。
- Kaggle Data Explorer のルートは意図的に `README.md` + `metadata.parquet` のみ。
- 現在の Kaggle Usability: **10.00 / 10**。
- 最終検証済みリリースは約 **1.03 GB**で、5 GB のハード上限を十分下回ります。

## リリース原則

- Smithsonian 公式メタデータを source of truth とします。
- レコードメタデータと、実際に選択した画像メディア項目の両方が明示的に `CC0` である必要があります。
- Smithsonian 公式 IDS derivative を優先し、最大辺の目標を 512 px とします。
- 1つの `object_id` は train/validation/test のどれか1つにのみ所属します。
- 25,000 行を無理に満たすことより品質を優先します。
- センシティブまたは曖昧な資料は自動公開せず、レビュー対象として隔離します。
- 3D、音声、動画、大規模 OCR/文書コーパス、自由形式の LLM キャプションはベースデータセットに含めません。

## ビルド概要

- Discovery でメディア単位の CC0 候補 **97,718 件**を収集しました。
- Eligibility filtering の結果は **eligible 90,451 / review-required 639 / rejected 6,628** です。
- 画像ダウンロード前の balanced selection で **18,321 オブジェクト**から正確に **25,000 行**を選択しました。
- 必須の 1K pilot は HTTP/デコード **1,000 / 1,000 成功**で package-size gate を通過しました。
- Production collection では **24,972 枚**を保持しました。再試行後も 25 件の source derivative が HTTP 404、3 件が最小 256 px 未満だったため、無理な補充は行っていません。
- QA で全 JPEG を再デコードし、SHA256 完全重複 0、重複 `media_id` グループ 0 を確認しました。
- モデル用テキストは Smithsonian のフィールドのみから生成し、保持行の 100% で非空、最大 512 文字です。元の `description` は完全なまま保持します。
- 最終リリース検証では画像、権利、寸法、split leakage、checksum の各 gate をすべて通過しました。
- CLIP ViT-B/32 embedding は任意の side artifact であり、ベースリリースからは意図的に除外しています。

## 権利ゲート

レコード単位のメタデータライセンスだけから画像の権利を推測しません。レコードメタデータが CC0 でも、添付画像に利用制限がある場合があります。自動 eligibility には次の3条件すべてが必要です。

1. `content.descriptiveNonRepeating.metadata_usage.access == "CC0"`
2. media `type == "Images"`
3. 選択したその media item の `usage.access == "CC0"`

それ以外はポリシー設定に従って拒否またはレビュー対象にします。

## パイプライン

収集フローでは、権利・品質・split の gate を次の順序で維持します。

```text
discover_metadata.py -> build_candidate_tables.py -> select_candidates.py
-> run_pilot.py -> download_images.py -> qa_images.py
-> build_metadata.py -> create_splits.py -> build_starter.py
-> build_release.py -> validate_release.py
```

大規模な Phase 2 収集は常に明示的に実行します。`data/` 以下の大容量生成物は Git の対象外です。

## 開発環境

Python 3.11 以上をサポートします。

```powershell
python -m pip install -e ".[data,dev]"
python -m pytest -q
python -m ruff check .
```

CI matrix は Python 3.11 と 3.12 で同じテストを実行します。

## 安全なメタデータスモークテスト

このコマンドは Smithsonian の **metadata shard のみ**をダウンロードし、小規模な代表 unit 集合から最大 250 件の CC0 image-media 候補を生成します。コレクション画像はダウンロードしません。

```powershell
python scripts/discover_metadata.py
```

完全な再ビルドでは、明示的な output/report パスと `--all-preferred-units --target ...` を指定します。CLI がスモークテストの既定値を勝手に大規模クロールへ変えることはありません。

## Smithsonian API キー

bulk metadata source は公開されており API キーは不要です。Smithsonian API を使用するスクリプトでは、自分の data.gov キーを環境変数で設定し、Git にはコミットしないでください。

```powershell
$env:SMITHSONIAN_API_KEY = "..."
python scripts/probe_sources.py
```

## リポジトリ構成

```text
config/                     収集・eligibility ポリシー
docs/                       出典、権利、schema、discovery、Kaggle 公開ノート
src/smithsonian_image_text/ metadata、filtering、image、text、split ロジック
scripts/                    discovery から release/validation までのエントリポイント
tests/                      ネットワーク不要の unit tests
data/                       ローカルビルド生成物。大容量ファイルは gitignore
```

## ドキュメント

- `docs/SOURCES.md`
- `docs/RIGHTS_POLICY.md`
- `docs/SCHEMA_RESEARCH.md`
- `docs/DISCOVERY_STRATEGY.md`
- `docs/DISTRIBUTION.md`
- `docs/KAGGLE_PUBLISHING.md`

機械可読な制御設定は `config/collection.yaml` と `config/eligibility_rules.yaml` にあります。
