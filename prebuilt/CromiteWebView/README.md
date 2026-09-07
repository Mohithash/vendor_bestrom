# CromiteWebView

Cromite's SystemWebView build, shipped instead of the AOSP prebuilt in
`external/chromium-webview`.

| | |
| --- | --- |
| Upstream | https://github.com/uazo/cromite |
| Release | `v148.0.7778.168-cb3baf14f52eb4365d017f640f85310735c19b79` (2026-05-21) |
| Asset | https://github.com/uazo/cromite/releases/download/v148.0.7778.168-cb3baf14f52eb4365d017f640f85310735c19b79/arm64_SystemWebView.apk |
| versionName / versionCode | 148.0.7778.168 / 777816801 |
| Package | `com.android.webview` |
| minSdk / targetSdk | 29 / 36 |
| Size | 297,580,352 bytes |
| License | GPL-3.0 with Chromium's BSD-3-Clause base (`LICENSE`, `LICENSE.chromium`) |

`CromiteWebView.apk` sha256
`dd690edc7ba909bfc095e798457cb874ab2d6ff1f63b980ed67cae5d725a8d14`

## Source

The binary is built from https://github.com/uazo/cromite at tag
`v148.0.7778.168-cb3baf14f52eb4365d017f640f85310735c19b79`, which is the
complete corresponding source for the GPL-3.0 parts of this APK. Cromite's
patch set applies on top of Chromium 148.0.7778.168
(https://chromium.googlesource.com/chromium/src at tag `148.0.7778.168`), whose
BSD-3-Clause notice is in `LICENSE.chromium`.

## Verification

The shipped sha256 is an attested value, not just an observed one. GitHub
publishes a Sigstore-signed release attestation for the artifacts of that tag,
and the APK in this directory is one of its subjects:

    curl -s https://api.github.com/repos/uazo/cromite/attestations/sha256:dd690edc7ba909bfc095e798457cb874ab2d6ff1f63b980ed67cae5d725a8d14

    200, one attestation. Decoding bundle.dsseEnvelope.payload (base64,
    application/vnd.in-toto+json):
      predicateType  https://in-toto.io/attestation/release/v0.2
      predicate      repository uazo/cromite, repositoryId 257841809,
                     tag v148.0.7778.168-cb3baf14f52eb4365d017f640f85310735c19b79
      subject        arm64_SystemWebView.apk
                     sha256 dd690edc7ba909bfc095e798457cb874ab2d6ff1f63b980ed67cae5d725a8d14
    Signing certificate: issuer O="GitHub, Inc." CN="Fulcio Intermediate l1",
    subject O="GitHub, Inc." CN=Attester, SAN URI
    https://dotcom.releases.github.com.

So the exact bytes here are bound by a signature to that release of that
repository. That is artifact provenance; key identity is a separate claim and
it is still uncorroborated. Cromite publishes no APK signer fingerprint - the
`49F37E74DEE483DCA2B991334FB5A0200787430D0B5F9A783DD5F13695E9517B` value in its
README is the F-Droid *repository index* signing key, a different artifact -
and `cromite.org` / `www.cromite.org` do not resolve from the build host. The
signer below is therefore recorded so a future substitution is detectable, not
matched against anything the project publishes.

    apksigner verify --print-certs CromiteWebView.apk
    Verified using v2 scheme (APK Signature Scheme v2): true   (no v1, no v3)
    certificate DN:          CN=CromiteOrg
    certificate SHA-256:     633fa41d8211d6d0916a819b89668c6de92e64232da67f9d16fd81c3b7e923ff
    certificate SHA-1:       f9c25477fb23ff80e93641270742d90fa58a9946

The APK is shipped byte for byte (`presigned` + `preprocessed`), so the
installed copy hashes to the same value and keeps that v2 block.

## Updating

Cromite's SystemWebView asset comes from a different CI workflow than its
browser releases and lags them; some releases carry no `arm64_SystemWebView.apk`
at all (the v151 beta ships only `arm64_ChromePublic.apk`). Check before every
BestROM release:

1. Find the newest release at https://github.com/uazo/cromite/releases that
   has an `arm64_SystemWebView.apk` asset, and download it.
2. `sha256sum` it, then run the attestation call above with the new digest. It
   must return 200 with subject `arm64_SystemWebView.apk` and a predicate whose
   `repository` is `uazo/cromite` and whose `tag` is the release being taken. A
   404 there means the artifact is not attested - stop.
3. `apksigner verify --print-certs`: still `CN=CromiteOrg`, still cert SHA-256
   `633fa41d...`. A changed key is a stop, not a note.
4. Refresh `LICENSE` from that tag and `LICENSE.chromium` from the matching
   Chromium tag.
5. Move the `PREBUILTS` entry in `vendor/bestrom/tools/fetch-prebuilts.sh`,
   `CromiteWebView.apk.sha256` and this file's version table, sha256 and tag
   together, and re-check the size line in `vendor/bestrom/CHANGELOG.md`.
   Then delete the local APK and re-run the script, so the new URL, size and
   digest are proven before anyone else syncs.

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
