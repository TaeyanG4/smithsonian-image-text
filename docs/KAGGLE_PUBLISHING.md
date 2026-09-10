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
same score was initially observed after Dataset Version 2 reached `READY`; the
remaining zero-valued criteria at that point were `fileDescriptionScore` and
`columnDescriptionScore`.

On 2026-09-11 the V2 Data Explorer metadata was synchronized through Kaggle's
logged-in, same-origin web mutation. Readback then reported **14/14 exact file
descriptions and 91/91 exact column descriptions**. The mutation response
reported `score: 1` with every component score equal to `1`, and a page refresh
showed **Usability 10.00** with no pending Usability actions.

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

Kaggle CLI 2.2.2 explicitly shipped a file/column description metadata fix
([#1055](https://github.com/Kaggle/kaggle-cli/pull/1055)), and the installed
2.2.4 client contains that conversion code. Even so, both metadata-only update
and a full V2 upload left this dataset's analyzed Data Explorer descriptions
empty. Treat the live Data Explorer readback, not a successful CLI response, as
the persistence check.

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

Kaggle's internal `UpdateDatabundleMetadataExternal` endpoint returns
`401 UNAUTHENTICATED` for both the ordinary Kaggle API bearer token and an access
token produced by `kaggle auth print-access-token`, even when the anti-CSRF
cookie/header pair is primed. The generated frontend contract for
`ReanalyzeDatabundleVersion` was also verified to accept only
`databundleVersionId`, but a request using the real V1 databundle ID returned
`404 NOT_FOUND` with both public and API-token sessions.

A normal CLI version upload was tested as well. Dataset Version 2
(`datasetVersionId=19565377`, `databundleVersionId=20680782`) was created with
the metadata-bearing release directory and reached `READY`, but Data Explorer
still reported **0/14 file descriptions and 0/91 column descriptions**. Therefore
creating another dataset version is not a valid workaround for this issue.

The score-aware route that did work is the same route used by Kaggle's logged-in
web application. It sends the browser's existing same-origin session together
with `X-XSRF-TOKEN` and `X-Kaggle-Build-Version`; the session cookie itself does
not need to be copied or exported. To generate the exact validated batch for the
current live version:

```powershell
python scripts/kaggle_usability.py --browser-script
```

This writes `tmp_research/kaggle_usability_browser_sync.js`. The generated file
contains no credentials. Open the target Kaggle dataset page while logged in,
open the browser developer console, paste the script, and execute it. It updates
one live Data Explorer file per request, including any validated live columns,
with a short delay between requests. Do not copy browser cookies into shell
scripts or commit them to the repository.

After the descriptions are saved in Kaggle, rerun:

```powershell
python scripts/kaggle_usability.py
```

The audit should report 14/14 file descriptions and 91/91 column descriptions.
Kaggle's anonymous/public `GetDatasetUsabilityRating` read model can lag behind
the mutation response; after the successful 2026-09-11 sync it briefly continued
to return the old `0.8235294` value even though the mutation returned `score: 1`
and the refreshed logged-in page displayed `Usability 10.00`.
