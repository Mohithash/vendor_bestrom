# CromiteWebView

Cromite's SystemWebView build, shipped instead of the AOSP prebuilt in
`external/chromium-webview`.

| | |
| --- | --- |
| Source | https://github.com/Mohithash/cromite, branch `bestrom-148` (BestROM fork of https://github.com/uazo/cromite) |
| Base | Cromite `v148.0.7778.168-cb3baf14f52eb4365d017f640f85310735c19b79` (Chromium 148.0.7778.168) |
| Release | `v148.0.7778.168-bestrom.1` |
| Asset | https://github.com/Mohithash/cromite/releases/download/v148.0.7778.168-bestrom.1/arm64_SystemWebView.apk |
| versionName / versionCode | 148.0.7778.168 / 777816801 |
| Package | `com.android.webview` |
| minSdk / targetSdk | 29 / 36 |
| Size | 297,580,352 bytes |
| Signer | BestROM WebView key (RSA-4096, certificate SHA-256 `ffa0f9a46ef930ce217540e6e5bf78a606d834e5cebf7d48e70e3e2057d59d90`) |
| License | GPL-3.0 with Chromium's BSD-3-Clause base (`LICENSE`, `LICENSE.chromium`) |

`CromiteWebView.apk` sha256
`b83dc3b529d76d8c5be08caa3ecab9822d1aa40d298ec92380c5b540b5dd1b7d`

## Source

The binary is built by BestROM from https://github.com/Mohithash/cromite,
branch `bestrom-148`, which is Cromite's release tag
`v148.0.7778.168-cb3baf14f52eb4365d017f640f85310735c19b79` plus two patches
of our own:

- `WebView-leave-the-dangling-raw_ptr-detector-off.patch` - Cromite turns
  Chromium's dangling raw_ptr detector on for every target and its verdict
  is a crash of the process. In WebView that process is the host app, which
  has no setting to turn it off; upstream WebView never enables it. The
  WebView build disables the feature next to the other process-global
  allocator features it already refuses.
- `WebView-clear-the-Vulkan-provider-pointer-before-releasing-it.patch` -
  the pointer the detector complained about: the Vulkan draw functor kept a
  stale pointer to its context provider between `OnContextDestroyed` and
  `OnDestroyed`. It is now cleared before the provider is released.

That branch is the complete corresponding source for the GPL-3.0 parts of
this APK. Cromite's patch set applies on top of Chromium 148.0.7778.168
(https://chromium.googlesource.com/chromium/src at tag `148.0.7778.168`),
whose BSD-3-Clause notice is in `LICENSE.chromium`.

## Build

Cromite's own recipe, outside GitHub Actions: Chromium at the tag with
`gclient` (`target_os = android`, PGO profiles), the five dependency
checkouts Cromite absorbs (`v8`, `third_party/skia`, `third_party/perfetto`,
`third_party/boringssl/src`, `third_party/devtools-frontend/src`) folded
into the top-level git, every entry of `build/cromite_patches_list.txt`
applied with `git am`, then

    gn gen --args="target_os=\"android\" target_cpu=\"arm64\" $(cat cromite/build/cromite.gn_args) system_webview_package_name=\"com.android.webview\" enable_trybot_verification=false" out/arm64_webview
    autoninja -C out/arm64_webview system_webview_apk

with `android_keystore_*` pointing at the BestROM WebView key. The unstripped
`libwebviewchromium.so` of each release is kept with the build so device
traces symbolize.

## Verification

There is no GitHub attestation for this asset (it is not built by Actions),
so `fetch-prebuilts.sh` carries it with the `sha256` mode: the digest in the
`PREBUILTS` entry is the digest of the published asset, checked on every
fetch, and the entry above records it. What binds the bytes to a source is
the release on `Mohithash/cromite`, whose tag points at the branch that
produced them.

    apksigner verify --print-certs CromiteWebView.apk
    Verified using v2 scheme (APK Signature Scheme v2): true
    certificate DN:          CN=BestROM WebView, O=BestROM, C=IN
    certificate SHA-256:     ffa0f9a46ef930ce217540e6e5bf78a606d834e5cebf7d48e70e3e2057d59d90

The key lives outside the tree with the other BestROM private keys. The APK
is shipped byte for byte (`presigned` + `preprocessed`), so the installed
copy hashes to the same value and keeps that v2 block; the framework accepts
it as the WebView provider because it is preinstalled, and only a build
signed with the same key can update it.

## Updating

1. Rebase `bestrom-148` (or a new `bestrom-<major>` branch) onto Cromite's
   next release tag that carries a WebView build; check that both patches
   still apply and whether upstream took either of them.
2. Build and sign as above; publish the APK as a release on
   `Mohithash/cromite` whose tag names the branch.
3. Move the `PREBUILTS` entry in `vendor/bestrom/tools/fetch-prebuilts.sh`
   (URL, sha256, size) and this file's version table together; refresh
   `LICENSE` and `LICENSE.chromium` from the tags. Then delete the local APK
   and re-run the script, so the new URL, size and digest are proven before
   anyone else syncs.
4. `apksigner verify --print-certs`: still `CN=BestROM WebView`, still cert
   SHA-256 `ffa0f9a4...`. A changed key is a stop, not a note.

## Network behaviour

Cromite's manifest still declares the stock WebView service set -
`AwVariationsSeedFetcher`, `VariationsSeedServer`, `MetricsBridgeService`,
`MetricsUploadService`, `AwComponentUpdateService`, `AwMinidumpUploadJobService`,
`CrashReceiverService` - which reads badly until the binary is checked. The
endpoints those services need are absent from both the dex and
`lib/arm64-v8a/libwebviewchromium.so`: no `clientservices.googleapis.com`, no
`chrome-variations`, no `update.googleapis.com`, no `/service/update2`, no
`clients2.google.com`. The variations/Finch seed fetch, the metrics upload and
the crash upload have nowhere to go, so the declared services are inert. That
is the privacy win.

The cost is on the same line. With the component updater dead, WebView receives
no CRLSet certificate-revocation updates and no other component refreshes,
ever, between ROM releases - the AOSP prebuilt it replaces had those components
live. Combined with the version lag below, the "Updating" section above is the
only mechanism keeping this component current.

## Version lag

148.0.7778.168 (2026-05-21) is roughly four Chrome majors and three and a half
months of Chromium security fixes behind the 152.0.7977.64 AOSP prebuilt it
replaces, on the component that renders untrusted web content for every app in
the image. This is structural rather than a snapshot - see "Updating". It is
the real cost of the change and it is a deliberate trade against Cromite's
privacy patches and de-Googled renderer.

## Notes

Cromite keeps the AOSP package name `com.android.webview`, so the framework's
provider list needs no change. `vendor/voltage/overlay/common` already overlays
`frameworks/base/core/res/res/xml/config_webview_packages.xml` and its
`com.android.webview` entry is `availableByDefault="true"` and
`isFallback="true"` with no `<signature>`; a preinstalled provider skips the
signature check regardless of key, because
`WebViewUpdateServiceImpl2.providerHasValidSignature` returns true for any
system app, and the `isFallback` flag makes the boot path install and enable
the provider for every user.

A BestROM overlay of that file was written and then dropped: it can never take
effect. aapt2 overlay priority follows `PRODUCT_PACKAGE_OVERLAYS` order with the
first root winning, and a product makefile's own additions always flatten after
the ones it inherits, so `vendor/bestrom/overlay/common` cannot outrank
`vendor/voltage/overlay/common` for a file both carry. It would also have bought
nothing: the only thing the `description` attribute feeds is
`WebViewProviderInfo.description`, and Settings' WebView picker labels each
provider from `ApplicationInfo` instead (`WebViewAppPicker.loadLabel`). The four
Google WebView entries Voltage lists stay in the config and stay unresolved,
which is what already happens today.

## Fetching

`CromiteWebView.apk` is **not in git**. It is 297 MB: GitHub refuses any single
file over 100 MB on push, and Git LFS only moves the problem, because a free
account gets 1 GB of LFS bandwidth a month and a 297 MB object exhausts it in
three clones - after which `repo sync` fails for everyone, not just the
maintainer.

The APK is downloaded instead, by

    vendor/bestrom/tools/fetch-prebuilts.sh

which checks the size, the sha256 in `CromiteWebView.apk.sha256` and the
attestation call above before it moves the file into place, and leaves nothing
behind if any of the three fails. It is idempotent and costs no network once
the file is there, so `build-bestrom-run.sh` runs it before every build.
`config/branding.mk` hard-errors if the APK is still missing.

Set `BESTROM_SKIP_ATTESTATION=1` to build without reaching api.github.com. The
size and digest are still enforced; only the provenance check is dropped.

When taking a newer release, update the URL, sha256 and size in the
`PREBUILTS` table of that script together with the version table above and
`CromiteWebView.apk.sha256`.
