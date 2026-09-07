# LeanType

LeanType, LeanBit Lab's HeliBoard fork, shipped instead of AOSP LatinIME.

| | |
| --- | --- |
| Upstream | https://github.com/LeanBitLab/LeanType |
| Release | `v4.2.0` (2026-09-05) |
| Asset | https://github.com/LeanBitLab/LeanType/releases/download/v4.2.0/1-LeanType_4.2.0-standard-release.apk |
| Package | `com.leanbitlab.leantype` |
| IME | `com.leanbitlab.leantype/helium314.keyboard.latin.LatinIME` |
| minSdk / targetSdk | 23 / 35 |
| Size | 12,573,686 bytes |
| License | GPL-3.0 (`LICENSE`; fork of HeliBoard / OpenBoard / AOSP LatinIME) |

`LeanType.apk` sha256
`e633bddd9211c6d0ab115c10b331db9584ff773108a884550d9a70ff35cc6409`

## Source

The binary is built from https://github.com/LeanBitLab/LeanType at tag `v4.2.0`,
which is the complete corresponding source for this GPL-3.0 APK. `LICENSE` is
the upstream text at that tag.

## Verification

    apksigner verify --print-certs 1-LeanType_4.2.0-standard-release.apk
    Verified using v1/v2/v3 schemes: true
    certificate DN:          CN=LeanBit Lab, OU=Dev, O=LeanBitLab, L=Bangalore, ST=Karnataka, C=IN
    certificate SHA-256:     ac7360ae311a36f2cc1caf1dad4848e18e191c55aaf128838fc34c92c6838016
    certificate SHA-1:       abc853d74881a17292676eb47262ede638f02492

That signer digest is the value f-droid.org publishes for
`com.leanbitlab.leantype` in `index-v2.json`, and F-Droid's own build
(https://f-droid.org/repo/com.leanbitlab.leantype_4108.apk, 4.1.8) was
downloaded and checked: identical certificate, `ac7360ae...`. So the GitHub
artifact carries the signing identity F-Droid distributes, and - because this
APK ships byte for byte with its signature preserved (`presigned` +
`preprocessed`) - an update from F-Droid or from GitHub installs over the system
copy instead of being refused for a signature mismatch. That is the whole
reason the module is not `default_dev_cert`.

LeanType publishes no checksum file and GitHub returns no release attestation
for the repository, so the sha256 above is observed on download; it detects a
future substitution, not a bad download today.

## Updating

1. Take the newest `1-LeanType_<version>-standard-release.apk` from
   https://github.com/LeanBitLab/LeanType/releases. F-Droid trails GitHub
   (4.1.8 when 4.2.0 was current), so GitHub is the source; F-Droid is the
   user-facing update channel.
2. `apksigner verify --print-certs`: the certificate SHA-256 must still be
   `ac7360ae311a36f2cc1caf1dad4848e18e191c55aaf128838fc34c92c6838016`. A
   changed key is a stop - it would also break every device updating from
   F-Droid.
3. Keep the `standard` flavor (see below); confirm the IME id in
   `packages/apps/BestromPreinstaller` still resolves if the component ever
   moves.
4. Refresh `LICENSE` from the new tag.
5. Move the APK and this file's version table and sha256 together.

## Installed size

64 MB installed, against LatinIME's 22 MB: 12.6 MB of APK, 32,513,752 B of odex
and 18,912,260 B of vdex. LatinIME's 20 MB was mostly dictionary assets and
compiled to a 2.3 MB odex; LeanType's is mostly code. The vdex is large because
LeanType's `classes.dex` is stored compressed in the APK, so ART has to keep its
own copy. This is the largest single line item in the WebView-plus-keyboard
swap and it belongs in the release notes.

`PRODUCT_DEXPREOPT_SPEED_APPS` no longer names the keyboard, where it named
LatinIME - but that recovers nothing, and the odex did not change size when the
entry was dropped. `device/xiaomi/peridot/device.mk` sets
`PRODUCT_DEX_PREOPT_DEFAULT_COMPILER_FILTER := speed`, so every app on this
device is AOT-compiled whole whether or not it is in that list; the list is kept
accurate rather than carrying an entry that does nothing. Getting the 42 MB back
would mean changing that device-wide filter, which is a decision about every app
in the image.

## Variant

The `standard` flavor, not `standardfull` or `offline`.

`standardfull` is the same app plus `REQUEST_INSTALL_PACKAGES`: a preinstalled
system keyboard that can side-load packages, updating itself outside the OTA,
is the wrong shape for a ROM.

`offline` drops `INTERNET` entirely, which is the stronger privacy story, but it
is a different package name (`com.leanbitlab.leantype.offline`), so it is not
what F-Droid publishes and its signer cannot be matched against a published
index; its five plugins also have to be side-loaded by hand.

No flavor bundles a cloud AI key. Cloud proofreading in `standard` is opt-in and
requires the user to paste their own key.

## Network behaviour

`standard` is not "the offline build plus a permission". It carries the whole
in-app updater - UI, GitHub query and download - and only lacks the permission
to install what it downloads. From the shipped dex:

* `settings.screens.UpdatesScreenKt` queries
  `https://api.github.com/repos/LeanBitLab/HeliboardL/releases/latest`, picks
  the asset whose name contains `standard` but not `standardfull`, and hands it
  to `DownloadManager`.
* `pref_auto_check_updates` is read with a default of `true`, so that check is
  **on by default**.
* Five more `https://api.github.com/repos/LeanBitLab/*-Plugin/releases/latest`
  calls sit in the plugin preference screens.

What matters for a system keyboard is where those fire, and the answer is good:
nothing runs at boot or when the keyboard starts. `pref_auto_check_updates` is
read in exactly one settings composable, WorkManager is present only as
`PluginWorkerFactory` for plugin downloads, and there are no Firebase, GMS or
analytics SDK classes at all (`com.google.firebase` appears only as an okhttp
platform-detection string; `CrashReportExceptionHandler` writes a local
`crash_reports.zip` with no upload endpoint). Every request needs the user to
open a settings screen first.

Consequence of shipping `standard` on a system partition: the in-app update it
offers cannot complete, because without `REQUEST_INSTALL_PACKAGES` the install
step has no permission and the user cannot grant an appop for a permission the
app does not declare. That dead end is accepted deliberately - **F-Droid is the
update channel for this keyboard**, and it works because the signature is
preserved (see "Verification").

## Default IME selection

LeanType declares a single locale-less dummy subtype (`res/xml/method_dummy`),
because HeliBoard forks manage languages inside the app rather than publishing
them to the framework, and `bool/im_is_default` is false outside ca/da/fa/ka/ta.
`InputMethodInfoUtils.getMinimumKeyboardSetWithSystemLocale` therefore matches
nothing, and with LatinIME gone the framework would enable and select no
keyboard at all on first boot.

`packages/apps/BestromPreinstaller` seeds
`Settings.Secure.ENABLED_INPUT_METHODS` and
`Settings.Secure.DEFAULT_INPUT_METHOD` from `BootCompletedReceiver.onReceive`,
before anything else it does, and only when the latter is empty.
`InputMethodManagerService` registers a `SecureSettingsChangeCallback` on both
keys, so the write takes effect in the same boot, and it persists for every boot
after. On a dirty flash the framework clears the stale LatinIME selection
itself - `postInputMethodSettingUpdatedLocked` finds the enabled list empty and
resets the selection - so the seeder sees an empty value and runs there too.

## Freezer

Unlike LatinIME, LeanType has a launcher entry
(`helium314.keyboard.settings.SettingsActivity`), so Freezer's
`SYSTEM_NO_LAUNCHER` hard-block does not cover it. It is protected by the
`ManageVerdict.IME` rule instead, which blocks any package in
`InputMethodManager.enabledInputMethodList` - i.e. the protection depends on the
IME seed above having run. `CromiteWebView` declares no launcher activity, like
the AOSP WebView it replaces, so `SYSTEM_NO_LAUNCHER` still covers it.

## Spell checker

LatinIME's `AndroidSpellCheckerService` was the only spell checker in the image.
LeanType publishes its own
(`helium314.keyboard.latin.spellcheck.AndroidSpellCheckerService`, ~40 locale
subtypes), so the Settings spell-checker row stays populated.
