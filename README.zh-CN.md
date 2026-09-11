# Smithsonian 25K 博物馆图像-文本数据集

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md)

[![CI](https://github.com/TaeyanG4/smithsonian-image-text/actions/workflows/ci.yml/badge.svg)](https://github.com/TaeyanG4/smithsonian-image-text/actions/workflows/ci.yml)

用于将经过版权审计的 Smithsonian Open Access 资料构建为图像-文本数据集并发布到 Kaggle 的可复现工具链。

**Kaggle:** [Smithsonian 25K Museum Image-Text Dataset](https://www.kaggle.com/datasets/taeyangg4/smithsonian-25k-museum-image-text)

**当前公开版本：**24,972 张 CC0 图像、丰富元数据、防泄漏数据划分，以及平衡的 5K 入门子集。

## 当前版本

Dataset Version 3 是当前 Kaggle 公开版本。经过验证的图像行和 canonical metadata 保持不变，只对 Kaggle 文件布局进行了整理，让用户能够更快找到核心表和文档。

- 已发布 **24,972 张** JPEG 图像。
- 从 4,621 个对象构建的平衡 **5,000 行**入门子集。
- **train 19,979 / validation 2,498 / test 2,495** 行，`object_id` 重叠为 0。
- canonical `metadata.parquet` 的 **43/43** 列均具有 Data Explorer 描述。
- Kaggle Data Explorer 根目录刻意保持精简，仅包含 `README.md` + `metadata.parquet`。
- 当前 Kaggle Usability：**10.00 / 10**。
- 最终验证版本约 **1.03 GB**，明显低于 5 GB 硬上限。

## 发布原则

- 以 Smithsonian 官方元数据作为 source of truth。
- 记录级元数据和实际选中的图像媒体项都必须明确标记为 `CC0`。
- 优先使用 Smithsonian 官方 IDS derivative，目标最大边长为 512 px。
- 每个 `object_id` 只能出现在 train/validation/test 中的一个划分里。
- 不强行凑满 25,000 行，质量优先。
- 对敏感或含义不明确的资料进行隔离审核，而不是自动发布。
- 基础数据集不包含 3D、音频、视频、大规模 OCR/文档语料或自由生成的 LLM caption。

## 构建摘要

- Discovery 阶段获得 **97,718** 个媒体级 CC0 候选项。
- Eligibility filtering 得到 **90,451 eligible / 639 review-required / 6,628 rejected**。
- 图像下载前的 balanced selection 从 **18,321 个对象**中精确选择 **25,000 行**。
- 必须执行的 1K pilot 实现 HTTP/解码 **1,000 / 1,000 成功**，通过 package-size gate。
- Production collection 最终保留 **24,972 张**图像。重试后仍有 25 个 source derivative 返回 HTTP 404，另有 3 个低于 256 px 最小要求，因此没有为凑数而回填。
- QA 再次成功解码所有保留的 JPEG，SHA256 完全重复为 0，重复 `media_id` 组为 0。
- 模型文本仅由 Smithsonian 字段组合而成，100% 的保留行均为非空，长度限制为 512 个字符，同时完整保留原始 `description`。
- 最终发布验证通过图像、版权、尺寸、split leakage 和 checksum 全部 gate。
- CLIP ViT-B/32 embedding 属于可选 side artifact，基础版本中刻意不包含它。

## 版权门控

不要仅根据记录级元数据许可证推断图像版权。记录元数据可能是 CC0，但附加图像仍可能带有使用限制。自动 eligibility 必须同时满足以下三个条件：

1. `content.descriptiveNonRepeating.metadata_usage.access == "CC0"`
2. media `type == "Images"`
3. 实际选中 media item 的 `usage.access == "CC0"`

其他情况按策略配置拒绝或送入人工审核。

## 流水线

采集流程按以下顺序保留版权、质量和 split gate：

```text
discover_metadata.py -> build_candidate_tables.py -> select_candidates.py
-> run_pilot.py -> download_images.py -> qa_images.py
-> build_metadata.py -> create_splits.py -> build_starter.py
-> build_release.py -> validate_release.py
```

大规模 Phase 2 采集始终需要显式执行。`data/` 下的大型输出不会提交到 Git。

## 开发环境

支持 Python 3.11 及以上版本。

```powershell
python -m pip install -e ".[data,dev]"
python -m pytest -q
python -m ruff check .
```

CI matrix 会在 Python 3.11 和 3.12 上运行相同测试。

## 安全的元数据 Smoke Test

该命令只下载 Smithsonian **metadata shard**，并从小型代表性 unit 集合中输出最多 250 个 CC0 image-media 候选项，不会下载馆藏图像。

```powershell
python scripts/discover_metadata.py
```

完整重建时，请显式指定 output/report 路径以及 `--all-preferred-units --target ...`。CLI 不会悄悄把 smoke-test 默认值变成大规模爬取任务。

## Smithsonian API Key

bulk metadata source 是公开的，不需要 API key。使用 Smithsonian API 的脚本请通过环境变量提供自己的 data.gov key，不要提交到 Git。

```powershell
$env:SMITHSONIAN_API_KEY = "..."
python scripts/probe_sources.py
```

## 仓库结构

```text
config/                     采集与 eligibility 策略
docs/                       来源、版权、schema、discovery 与 Kaggle 发布说明
src/smithsonian_image_text/ metadata、filtering、image、text 与 split 逻辑
scripts/                    从 discovery 到 release/validation 的入口脚本
tests/                      无网络依赖的 unit tests
data/                       本地构建产物；大型文件由 gitignore 忽略
```

## 文档

- `docs/SOURCES.md`
- `docs/RIGHTS_POLICY.md`
- `docs/SCHEMA_RESEARCH.md`
- `docs/DISCOVERY_STRATEGY.md`
- `docs/DISTRIBUTION.md`
- `docs/KAGGLE_PUBLISHING.md`

机器可读的控制配置位于 `config/collection.yaml` 和 `config/eligibility_rules.yaml`。

## 发布与凭证

重新构建本地数据集包不需要 Kaggle API key。本仓库不会保存 Kaggle、GitHub、Smithsonian、OAuth、浏览器会话或其他凭证。发布到 Kaggle 始终作为独立的认证操作执行，并且每次写入 Kaggle 元数据后都应通过 live readback 验证实际结果。
