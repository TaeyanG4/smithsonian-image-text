# Kaggle publishing and Usability notes

This document records the Kaggle-specific presentation and metadata details that
are easy to lose between releases.

## Cover image geometry

Kaggle CLI 2.2.4 uploads a dataset cover with two fixed crop rectangles:

- header: `560 x 280`, starting at `x=0, y=0`
- square dataset-card thumbnail: `280 x 280`, starting at `x=140, y=0`

The canonical cover is therefore rendered at exactly **560 x 280** by
`scripts/build_cover.py`. The four central tiles are deliberately contained in
the `x=140..420` safe area so the square thumbnail remains meaningful after
Kaggle crops and resizes it.

Do not replace the canonical cover with a larger landscape canvas without first
re-verifying Kaggle's uploader crop behavior. A larger source can look correct
locally while producing a partially cropped dataset card.

The current cover is built from actual released Smithsonian images, not generated
art, so the thumbnail remains an honest preview of the dataset.

## Usability checklist

The live Kaggle Usability detail endpoint currently evaluates these criteria:

- Subtitle
- Tags
- Overview / description
- Cover image
- Source / provenance
- Public notebook
- Update frequency
- License
- Preferred file format
- File descriptions
- Column descriptions

After the cover, source metadata, update frequency, and public starter notebook
were corrected, the live detailed score reached **0.8235294 (8.24 / 10)**. The
remaining zero-valued criteria are:

- `fileDescriptionScore`
- `columnDescriptionScore`

`dataset-metadata.json` contains the complete intended metadata. The release
builder now emits descriptions for all 14 top-level files analyzed by Kaggle and
descriptions for all 91 columns across `metadata.csv`, `metadata.parquet`, and
`splits.csv`.

## Why the normal CLI is not enough

`kaggle datasets metadata --update` persists dataset-level settings, including
source/provenance and expected update frequency, but Kaggle currently does not
propagate `resources[].description` and `resources[].schema.fields[].description`
into the existing Data Explorer metadata for this dataset.

`scripts/kaggle_usability.py` validates the exact live V1 file and column layout
and builds the Data Explorer metadata update plan. Its default mode is read-only:

```powershell
python scripts/kaggle_usability.py
```

An authenticated API-token attempt can be made with:

```powershell
python scripts/kaggle_usability.py --apply
```

At the time of this note, Kaggle's internal
`UpdateDatabundleMetadataExternal` endpoint returns `401 UNAUTHENTICATED` for
Kaggle API-token authentication even when the anti-CSRF token is primed. In
other words, the final file/column description save currently requires a
logged-in Kaggle web session. Do not automate or extract a browser session just
to bypass that boundary; use the normal Kaggle editor when a browser-authenticated
save is needed.

After the descriptions are saved in Kaggle, rerun:

```powershell
python scripts/kaggle_usability.py
```

The audit should report 14/14 file descriptions, 91/91 column descriptions, and
the live Kaggle Usability detail score should reach 1.0.

