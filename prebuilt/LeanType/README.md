# LeanType

LeanType, LeanBit Lab's HeliBoard fork, shipped instead of AOSP LatinIME.

This is a **BestROM build**, not the upstream release artifact: one commit on
top of `v4.2.0` defaults the keyboard to full size. See [Fork](#fork).

| | |
| --- | --- |
| Fork | https://github.com/Mohithash/LeanType branch `bestrom-17`, commit `f8c5ceb048037627a56d53d0e37c85ccdac38ff1` |
| Upstream | https://github.com/LeanBitLab/LeanType |
| Base | `v4.2.0` (2026-09-05), commit `1383390cb9c48b859f56b6499210cbccbd91996f` |
| Patch | `patches/0001-Default-to-100-keyboard-height-and-width.patch` |
| Package | `com.leanbitlab.leantype` |
| IME | `com.leanbitlab.leantype/helium314.keyboard.latin.LatinIME` |
| minSdk / targetSdk | 23 / 35 |
| Size | 12,474,651 bytes (unsigned; Soong signs it) |
| License | GPL-3.0 (`LICENSE`; fork of HeliBoard / OpenBoard / AOSP LatinIME) |

`LeanType.apk` sha256
`de98f92e85e7e4ee0ee9f701fdef1feb32132777bb6560b715e22dc09e9eeca7`

The package name, `versionCode` 4200, `versionName` 4.2.0, `targetSdk` and the
`arm64-v8a`/`armeabi-v7a` ABI set are identical to upstream's artifact; only the
two default values and the signature differ.

## Source

The binary is built from https://github.com/Mohithash/LeanType branch
`bestrom-17`, which is the complete corresponding source for this GPL-3.0 APK.
That branch is `LeanBitLab/LeanType` tag `v4.2.0` plus the single commit below;
`LICENSE` is the upstream text at that tag.

That branch does not have to be reachable for the offer to hold: the same commit
is kept here as
`patches/0001-Default-to-100-keyboard-height-and-width.patch`, so upstream tag
`v4.2.0` (`1383390cb9c48b859f56b6499210cbccbd91996f`) plus that one patch
reproduces the shipped source exactly.

    git clone https://github.com/LeanBitLab/LeanType -b v4.2.0 LeanType
    git -C LeanType am < patches/0001-Default-to-100-keyboard-height-and-width.patch

> **Release gate.** GPL-3.0 section 6 requires the offer above to resolve for
> anyone who receives an image carrying this APK. `Mohithash/LeanType` must
> exist and carry branch `bestrom-17` **before** an OTA or a public build ships
> the keyboard; check with
> `curl -sI https://github.com/Mohithash/LeanType/tree/bestrom-17 | head -1`.

## Fork

`LeanType: Default to 100% keyboard height and width`, two lines of
`app/src/main/java/helium314/keyboard/latin/settings/Defaults.kt`:

```
-    val PREF_KEYBOARD_HEIGHT_SCALE = arrayOf(0.77f, 0.45f)
+    val PREF_KEYBOARD_HEIGHT_SCALE = arrayOf(DEFAULT_SIZE_SCALE, DEFAULT_SIZE_SCALE)
-    val PREF_SIDE_PADDING_SCALE = Array(4) { 0.15f }
+    val PREF_SIDE_PADDING_SCALE = Array(4) { 0f }
```

Upstream ships 77% height (45% landscape) and 15% side padding. These are Kotlin
constants in `Defaults`, not resources, so no RRO can reach them, and nothing in
the app imports a settings file at first run - a fork build is the only way to
move them.

Both are plain multipliers read through `prefs.getFloat(key, default)`, so this
changes only the **default**. The Appearance sliders ("Keyboard height scale",
"Side padding scale") still work, and a user who has already moved either one
keeps their value; `AppUpgrade.kt` only rewrites keys that already exist, so no
migration is needed. `PREF_BOTTOM_PADDING_SCALE` (`arrayOf(1.05f, 0f)`, the
vertical space *under* the keyboard) is deliberately untouched.

On peridot (1220x2712, 480dpi, ~406x904dp) the portrait keyboard goes from 158dp
to 205.6dp, still under the 46%p (415dp) `config_max_keyboard_height` clamp, and
from 97.6% to 100% of the screen width. Landscape barely moves: `values-land`
sets `config_min_keyboard_height` to 45%p (~183dp), above the 176dp base, so the
0.45f landscape default was mostly being clamped away already.

### Building it

    git clone https://github.com/Mohithash/LeanType -b bestrom-17
    JAVA_HOME=<jdk17> ANDROID_HOME=<sdk> ./gradlew assembleStandardRelease

Needs JDK 17 (AGP 8.13.2, Kotlin 2.2.21, `compileOptions VERSION_17`), Gradle
8.13 via the wrapper, `compileSdk 36` and **NDK 28.0.13004108** -
`app/build.gradle.kts` carries a real `externalNativeBuild { ndkBuild }` for the
AOSP latinime native dictionary library, so the NDK is mandatory. The output at
`app/build/outputs/apk/standard/release/1-LeanType_4.2.0-standard-release.apk`
is unsigned; the repository ships no `keystore.properties`. That unsigned file is
what is committed here as `LeanType.apk` - do not hand-sign it.

## Signing

`Android.bp` sets `default_dev_cert: true`, so **Soong signs and zipaligns this
module like any other app in the image**, with `PRODUCT_DEFAULT_DEV_CERTIFICATE`
= `vendor/voltage-priv/keys/testkey` (`vendor/voltage-priv/keys/keys.mk:95`).
Nothing here is signed by hand.

The point of that shape, rather than `presigned: true` next to a hand-signed
APK, is release signing: `sign_target_files_apks` skips presigned modules
entirely, so a hand-signed keyboard would silently stay on the old key while
every other app in a release-signed build rotated to the new one. A signed
module rotates with the rest.

Verify the module's real output, not the source APK (`m LeanType` first):

    java -jar prebuilts/sdk/tools/linux/lib/apksigner.jar verify \
        --min-sdk-version 24 --print-certs \
        out/target/product/peridot/product/app/LeanType/LeanType.apk
    Verifies
    Verified using v2 scheme (APK Signature Scheme v2): true
    Verified using v3 scheme (APK Signature Scheme v3): true
    certificate DN:      EMAILADDRESS=android@android.com, CN=Android, OU=Android,
                         O=Android, L=Mountain View, ST=California, C=US
    certificate SHA-256: 89db0c4ba0bba146eb88c516bb50fc95d2d5fa635f902c6537eda9a2030e3f9a
    certificate SHA-1:   0a255b7ebb2ff5e3fd74ba9c4e533538bad66fbf

`--min-sdk-version 24` is required: Soong signs with `--disable-v1` for modules
whose minSdk is 24 or higher, and apksigner otherwise reads the APK's own
minSdk 23 and fails on the missing `META-INF/MANIFEST.MF`. Android verifies
v3 then v2; v1 is unused on this platform. Call the jar directly - the
`prebuilts/sdk/tools/linux/bin/apksigner` wrapper is broken in this tree.

The 16 KB `lib/*.so` alignment survives signing:
`out/host/linux-x86/bin/zipalign -c -P 16 -v 4 <installed apk>` reports
`Verification successful`.

### What this costs

The upstream artifact carried LeanBit Lab's key
(`ac7360ae311a36f2cc1caf1dad4848e18e191c55aaf128838fc34c92c6838016`, the digest
f-droid.org publishes for `com.leanbitlab.leantype`; F-Droid's own 4.1.8 build
was downloaded and confirmed to carry it). That is what let an F-Droid or GitHub
build install as an update over the system copy. **A differently signed fork
build ends that**: from here the keyboard can only be updated by an OTA, and an
F-Droid or GitHub install is refused for a signature mismatch. There is no
configuration that keeps both the changed defaults and the upstream signature -
the values are compiled-in constants.

`vendor/voltage-priv/keys/testkey` is the stock **AOSP test key**, whose private
half is public. Image-wide that is not a new exposure - every app is signed with
it today - but for this app it is a real change of protection: before the fork
the system keyboard could only be replaced by an APK holding LeanBit Lab's
private key, and now anyone can build one that installs as an update over the
app that sees every keystroke. That makes release-key signing a **prerequisite
for an official (`BESTROM_OFFICIAL`) build**, not a later cleanup. Because the
module is `default_dev_cert` rather than presigned, moving the ROM to real
release keys carries the keyboard with it and needs no change here.

## Updating

1. Rebase the fork commit onto the newest upstream tag in
   https://github.com/Mohithash/LeanType (branch `bestrom-17`) and rebuild per
   [Building it](#building-it). The upstream release APK cannot be used as-is
   any more - it would not carry the default change.
2. Drop the **unsigned** Gradle output in as `LeanType.apk`, refresh
   `patches/` with `git format-patch`, run `m LeanType` and confirm
   `apksigner verify --min-sdk-version 24 --print-certs` on the installed copy
   reports the `89db0c4b...` certificate. Do not sign the APK by hand.
3. Check `Defaults.kt` still has `PREF_KEYBOARD_HEIGHT_SCALE` and
   `PREF_SIDE_PADDING_SCALE` in that shape; upstream renaming or re-typing
   either one is the thing most likely to silently drop the change.
4. Keep the `standard` flavor (see below); confirm the IME id in
   `packages/apps/BestromPreinstaller` still resolves if the component moves.
5. Refresh `LICENSE` from the new tag.
6. Move the APK and this file's version table and sha256 together.

## Installed size

57,547,662 B installed, against LatinIME's 22 MB: 24,548,742 B of APK,
32,513,752 B of odex and 485,168 B of vdex. LatinIME's 20 MB was mostly
dictionary assets and compiled to a 2.3 MB odex; LeanType's is mostly code.
This is the largest single line item in the WebView-plus-keyboard swap and it
belongs in the release notes.

The installed APK is twice the size of the one committed here because Soong
uncompresses `classes*.dex` for dexpreopt. That trade is worth ~6.5 MB: the
vdex no longer has to carry ART's own copy of the dex (18,912,216 B when the
module was presigned and copied verbatim, 485,168 B now that Soong builds it).

`PRODUCT_DEXPREOPT_SPEED_APPS` no longer names the keyboard, where it named
LatinIME - but that recovers nothing, and the odex did not change size when the
entry was dropped. `device/xiaomi/peridot/device.mk` sets
`PRODUCT_DEX_PREOPT_DEFAULT_COMPILER_FILTER := speed`, so every app on this
device is AOT-compiled whole whether or not it is in that list; the list is kept
accurate rather than carrying an entry that does nothing. Getting the 33 MB back
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
index; its five plugins also have to be side-loaded by hand. Worth revisiting
now that the fork build has given up the F-Droid update path anyway - the
`Defaults.kt` change applies to that flavor unchanged.

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
* `pref_auto_check_updates` is read with a default of `true`, but the only thing
  that default does is decide whether the check-frequency row is shown on the
  Updates screen: it is read in one composable and used in one `if`, and no
  worker, alarm or receiver consults it. Left at upstream's value rather than
  patched, because flipping it would change a settings row and nothing else.
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
app does not declare. Since the fork build is signed with a BestROM key, an
F-Droid or GitHub install would be refused for a signature mismatch as well, so
**the OTA is the only update channel for this keyboard** (see "What this
costs"). The in-app updater is a dead end either way; it is also inert unless
the user opens the Updates settings screen.

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
