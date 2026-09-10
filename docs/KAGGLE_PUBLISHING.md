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

For Dataset Version 2, Kaggle's `data-original.jpg` was downloaded directly and
matched `docs/dataset-cover-image.jpg` byte-for-byte. The source is exactly
`560 x 280`; Kaggle's generated square card contains the four complete central
tiles, confirming that the live crop-safe layout survived publication.

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
same score was rechecked after Dataset Version 2 reached `READY`. The remaining
zero-valued criteria are:

- `fileDescriptionScore`
- `columnDescriptionScore`

`dataset-metadata.json` contains the complete intended metadata. The release
builder emits descriptions for all 14 top-level files analyzed by Kaggle and
descriptions for all 91 Data Explorer columns across `metadata.csv`,
`metadata.parquet`, and `splits.csv`. It can also describe nested release
resources, but those are not counted as Data Explorer root files. Kaggle does not
currently expose columns for `captions.jsonl`, so its locally documented schema
is not part of the live 91-column Usability target.

## Why the normal CLI is not enough

`kaggle datasets metadata --update` persists dataset-level settings, including
source/provenance and expected update frequency, but Kaggle currently does not
propagate `resources[].description` and `resources[].schema.fields[].description`
into the existing Data Explorer metadata for this dataset.

`scripts/kaggle_usability.py` validates the exact live Data Explorer file and
column layout and builds the metadata update plan. By default it audits the
latest `READY` version from Kaggle dataset history; a historical version can be
selected with `--dataset-version`. Its default mode is read-only:

```powershell
python scripts/kaggle_usability.py
```

An authenticated API-token attempt can be made with:

```powershell
python scripts/kaggle_usability.py --apply
```

At the time of this note, Kaggle's internal
`UpdateDatabundleMetadataExternal` endpoint returns `401 UNAUTHENTICATED` for
Kaggle API-token authentication even when the anti-CSRF token is primed. The
generated frontend contract for `ReanalyzeDatabundleVersion` was also verified
to accept only `databundleVersionId`, but a request using the real V1 databundle
ID still returned `404 NOT_FOUND` with both public and API-token sessions.

A normal CLI version upload was tested as well. Dataset Version 2
(`datasetVersionId=19565377`, `databundleVersionId=20680782`) was created with
the metadata-bearing release directory and reached `READY`, but Data Explorer
still reported **0/14 file descriptions and 0/91 column descriptions**. Therefore
creating another dataset version is not a valid workaround for this issue.

The remaining score-aware mutation is the logged-in web-app Data Explorer save.
Do not automate, extract, or replay a browser session just to bypass that auth
boundary; use the normal Kaggle editor when a browser-authenticated save is
needed.

After the descriptions are saved in Kaggle, rerun:

```powershell
python scripts/kaggle_usability.py
```

The audit should report 14/14 file descriptions, 91/91 column descriptions, and
the live Kaggle Usability detail score should reach 1.0.
