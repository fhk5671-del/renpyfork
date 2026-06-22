# RNX SDK Editing Workflow

This repository is the source/editing copy. The runnable SDK is
`C:\Users\super\Dropbox\renpy-8.4.1-rnx-sdk`.

## Core Rules

- Do source-tree edits first, then propagate them with `python tools\patch_rnx_sdk.py`.
- Do not make one-off SDK-only fixes unless you are only diagnosing. If an SDK fix is real, put it in the repo and make `patch_rnx_sdk.py` reproduce it.
- `renpy/blobstore.py` is the RNX/RSC/RSM helper. Do not reintroduce `renpy/custom_format.py`.
- After copying `.rpy` files into the SDK, ensure the copied file mtime is newer than any existing `.rsc`; stale compiled launcher/common scripts can silently win.
- The stock SDK at `C:\Users\super\Dropbox\renpy-8.4.1-sdk` is useful as a reference when the runnable RNX SDK needs an SDK-specific file restored.
- The RNX launcher uses its own persistent namespace, `launcher-rnx-4`, and its own multipersistent namespace, `launcher-rnx.renpy.org`. Do not change the stock SDK to accomplish launcher separation.
- User projects created by the RNX launcher are flat RNX projects: `project.json`, `script.rpy`, `options.rpy`, assets, and manifests live directly in the project root, not under a child `game\` folder.
- RNX projects are stamped in `project.json` with `"rnx_sdk_project": true`, `"sdk": "rnx"`, and `"rnx_layout": "flat"`. The RNX launcher recognizes these flat roots and filters external project-list entries to RNX-marked projects.
- The stock launcher does not understand RNX markers, but its normal project scan looks for a child `game\` folder. A flat RNX project root is therefore not identified by the stock launcher during ordinary scans. Standard-layout RNX test projects with `root\game\...` can still be seen by the stock launcher if the user points it at the same parent folder or manually adds them to `projects.txt`.
- Explicit command-line runs can still target any project or game directory path; launcher separation is meant to prevent accidental cross-listing, not to make the stock SDK unable to run a deliberately supplied path.

## Files That Are Safe To Sync Wholesale

These are intended to match the source tree in the RNX SDK:

- `renpy/blobstore.py`
- `renpy/premium_build.py`
- `renpy/loader.py`
- `renpy/script.py`
- `renpy/arguments.py`
- `renpy/config.py`
- `renpy/common/00build.rpy`
- `renpy/common/00motion_depth.rpy`
- `renpy/common/00voice_manifest.rpy`
- `renpy/translation/voice_manifest.py`
- `renpy/update/update.py`
- `renpy/exports/scriptexports.py`
- `launcher/game/archiver.rpy`
- `launcher/game/distribute.rpy`
- `launcher/game/distribute_gui.rpy`
- `launcher/game/front_page.rpy`
- `launcher/game/mac.rpy`
- `launcher/game/options.rpy`
- `launcher/game/project.rpy`

Keep that list centralized in `tools/patch_rnx_sdk.py`.

## Files Not To Sync Wholesale

Some SDK files differ from the source checkout even when the relevant RNX patch is tiny.

- Do not copy source `renpy/__init__.py` into the SDK. It expects source/git version metadata and can break SDK startup with missing version keys. Restore it from the stock SDK if needed, then only patch the required import.
- Do not copy source `renpy/main.py` into the SDK. The source tree can refer to APIs such as `renpy.python.compile_cache` that the packaged SDK does not expose. Restore it from the stock SDK if needed, then only patch the compiled module extension check.

## Premium Pack Rules

- Author manifest inputs include `game/rnx_premium.json`, `rnx_premium.json`, `.rnx/premium_build.json`, and `game/.rnx/premium_build.json`.
- Author manifests must not ship. The generated runtime file is `game/rnx_premium_policy.json`.
- Explicit inclusion is monotonic by tier: `non_premium` is available everywhere, `p10` is p10 and p15, and `p15` is p15-only.
- Lower explicit asset tiers win over broader higher-tier wildcards.
- Premium sidecar packs live outside the game directory under `premium-packs/`.
- Runtime policy must allow the generated sidecar archive names and both stripped-base and premium compiled scripts.

## Smoke Test

Use the fixture in `tmp\rnx_premium_smoke`. For flat-layout coverage, copy its
`game\` contents into a flat temporary project root and add an RNX `project.json`
marker.

Run:

```powershell
python tools\patch_rnx_sdk.py
$env:RENPY_LOG_TO_STDOUT = '1'
$sdk = 'C:\Users\super\Dropbox\renpy-8.4.1-rnx-sdk'
$exe = Join-Path $sdk 'renpy.exe'
$launcher = Join-Path $sdk 'launcher'
$project = "C:\Users\super\Documents\Ren'py Fork\tmp\rnx_premium_smoke"
$dest = "C:\Users\super\Documents\Ren'py Fork\tmp\rnx-premium-smoke-1.0-dists"
$out = "C:\Users\super\Documents\Ren'py Fork\tmp\rnx-premium-smoke-output.txt"
$err = "C:\Users\super\Documents\Ren'py Fork\tmp\rnx-premium-smoke-error.txt"
$args = @($launcher, 'distribute', $project, '--destination', $dest, '--package', 'gameonly', '--format', 'directory')
$argString = ($args | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join ' '
$p = Start-Process -FilePath $exe -ArgumentList $argString -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
$p.ExitCode
```

Expected results:

- No `launcher\traceback.txt`.
- Base output contains `game\archive.rnx` and `game\rnx_premium_policy.json`.
- `game\rnx_premium.json` is not shipped.
- `premium-packs\p10.rnx` and `premium-packs\p15.rnx` contain premium compiled scripts and marker files.
- Category packs such as `p10-images.rnx`, `p15-images.rnx`, `p10-video.rnx`, and `p15-video.rnx` contain only the tier-appropriate assets.
- Free/base output keeps explicitly non-premium files loose or in the base build, such as the smoke fixture's `assets/video/free_keep.webm`.
- Runtime policy allows script names as runtime archive members, for example `script.rsc`, not distributor paths such as `game/script.rsc`.

## Problems Already Hit

- Copying source `renpy/__init__.py` into the SDK broke startup because the SDK expects `version_name`, while the source file used different version metadata keys.
- Copying source `renpy/main.py` into the SDK broke startup because the SDK had `py_compile_cache`, while the source file referenced a different compile cache API.
- Synced `.rpy` files can be ignored when an older `.rsc` has a newer timestamp. `patch_rnx_sdk.py` now touches copied `.rpy` files after copying.
- The launcher can fail during init if `launcher/game/mac.rpy` depends on `distribute.py` before the `distribute` store module has initialized. `mac.rpy` now formats its Python-version path directly.
- Do not capture `project.Project` at `distribute.rpy` init time. The launcher project module may not be initialized yet. Use the runtime project instance's type inside `Distributor`.
- `renpy/script.py` needs compatibility guards for SDK/source parser and test APIs. Use `parser_has_parse_errors()` and guard `renpy.test.testexecution.register_testcase`.
- In captured Codex/PowerShell runs, Ren'Py text commands can traceback in `renpy/log.py` while flushing stderr. Set `$env:RENPY_LOG_TO_STDOUT = '1'` and use `Start-Process -Wait -PassThru -WindowStyle Hidden` with redirected output for distribution smoke tests.
- PowerShell `Get-ChildItem -Include` can match too broadly unless the path shape is exactly right. For cleanup of compiled files, enumerate files and filter by `Extension` explicitly.
- `Start-Process -ArgumentList @($args)` can split paths containing spaces, such as `Ren'py Fork`. Build one quoted argument string for smoke commands.
