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

The same commit is also kept here as
`patches/0001-Default-to-100-keyboard-height-and-width.patch`, so upstream tag
`v4.2.0` (`1383390cb9c48b859f56b6499210cbccbd91996f`) plus that one patch
reproduces the shipped source exactly:

    git clone https://github.com/LeanBitLab/LeanType -b v4.2.0 LeanType
    git -C LeanType am < patches/0001-Default-to-100-keyboard-height-and-width.patch

> **Source offer.** `https://github.com/Mohithash/LeanType` is public
> (checked 2026-09-08): branch `bestrom-17` is the fork commit above
> (`f8c5ceb0`), `main` mirrors upstream `LeanBitLab/LeanType`. Upstream's
> `main` has since moved to an untagged Kotlin rewrite with the same
> `versionCode`; the prebuilt stays on the `v4.2.0` tag until upstream tags a
> release, then `bestrom-17` is rebased onto it (a candidate rebase applies
> with one trivial conflict in `Defaults.kt`).
>
> Still open: the person who receives the image never reads this file. The
> same URL belongs somewhere they can reach it - an About or Legal source-offer
> string, or the OTA release notes. The generated NOTICE carries the GPL-3.0
> licence text, and a licence text is not an offer of source.

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

### Loose ends in the fork

Two, both deliberately left for the next fork bump rather than fixed with a
rebuild of a verified binary:

* The first-run wizard now argues with itself. `WelcomeWizard.kt:613` is a
  hardcoded English string reading "Adjust the height of the keyboard.
  Recommended: 77% for more square keys, 100% for taller keys.", above a slider
  that opens at the new 100% default. Drop the recommendation clause - the step
  is a slider, it does not need one - in the same commit that gets pushed for
  the source offer.
* Landscape height goes 0.45f -> 1.0f, and no one has looked at it on a screen.
  The clamp argument above is reasoning, not a measurement. If a landscape
  screenshot shows the text field crowded out, split the default back to
  `arrayOf(1.0f, 0.45f)`: portrait is what was actually asked for.

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

About 832 KB of that is dead weight: the APK carries a full `armeabi-v7a` slice
(`libjni_latinime.so` 801,488 B, `libimage_processing_util_jni.so` 20,380 B,
`libandroidx.graphics.path.so` 7,224 B, `libsurface_util_jni.so` 3,440 B) that
peridot can never load - the product inherits `core_64_bit_only.mk`, so
`Build.SUPPORTED_ABIS` is `arm64-v8a` alone and `NativeLibraryHelper` always
picks the 64-bit slice. It is carried twice, in `/product` and in the OTA
payload. Not a correctness problem, and not worth a rebuild on its own; fix it
on the next fork bump by adding `ndk { abiFilters += "arm64-v8a" }` to
`app/build.gradle.kts`, or an ABI split that keeps only `arm64-v8a`.

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

`offline` drops `INTERNET` entirely, which is the stronger privacy story. It was
rejected for being a different package name
(`com.leanbitlab.leantype.offline`), so not what F-Droid publishes and not
matchable against a published index - but **that reason is void now**: the fork
build is signed with the ROM key, so the F-Droid path is gone either way. What
remains against `offline` is that its five plugins must be side-loaded by hand
and that dictionaries cannot be downloaded in-app, only imported. The
`Defaults.kt` change applies to it unchanged, so switching is a one-line change
to [Building it](#building-it) plus a rebuild. Decide it deliberately rather
than by inheritance; on the permission table above, `offline` removes the entire
first row and everything that depends on it.

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

The updater is not the whole destination list. Everything else the shipped dex
can reach, and what triggers it:

* `https://generativelanguage.googleapis.com` (models `gemini-2.5-flash`,
  `gemini-2.5-pro`) and a Groq or OpenAI-compatible endpoint, for the optional
  "smart proofreading and rewriting" feature. `https://console.groq.com/keys`
  and `https://aistudio.google.com/app/apikey` appear only as links to the pages
  where a user gets a key.
* `https://huggingface.co/ggerganov/whisper.cpp` - `ggml-tiny-q5_1.bin`,
  `ggml-base-q5_1.bin`, `ggml-small-q5_1.bin`, downloaded if the user turns on
  on-device voice input.
* `https://dl.google.com/handwriting/models/*.fst.zip` and
  `https://dl.google.com/translate/offline/*`, per-language handwriting and
  offline translation packs.
* `https://codeberg.org/Helium314/aosp-dictionaries` - dictionary and emoji
  data the user picks per language.

**No credential is bundled.** `strings` over both `classes*.dex` for `AIza`,
`gsk_`, `hf_` and `sk-` literals returns nothing, so the cloud AI path cannot
fire until the user pastes a key of their own; the same check is worth repeating
on every version bump.

What matters for a system keyboard is where those fire, and the answer is good:
no request originates at boot or when the keyboard starts. `pref_auto_check_updates`
is read in exactly one settings composable, WorkManager is present only as
`PluginWorkerFactory` for plugin downloads, and there are no Firebase, GMS or
analytics SDK classes at all (`com.google.firebase` appears only as an okhttp
platform-detection string; `CrashReportExceptionHandler` writes a local
`crash_reports.zip` with no upload endpoint). Every request needs the user to
open a settings screen first.

Two receivers do register for `BOOT_COMPLETED`, so "nothing runs at boot" would
be too strong:

* `helium314.keyboard.latin.SystemBroadcastReceiver` - toggles the
  `SettingsActivity` component and re-initialises dictionaries. No network.
* `androidx.work.impl.background.systemalarm.RescheduleReceiver` - WorkManager's
  own, and it ships `android:enabled="false"`; WorkManager enables it only while
  work is pending. If a user starts a plugin download and reboots before it
  finishes, that download resumes at boot. Nothing else uses WorkManager.

Consequence of shipping `standard` on a system partition: the in-app update it
offers cannot complete, because without `REQUEST_INSTALL_PACKAGES` the install
step has no permission and the user cannot grant an appop for a permission the
app does not declare. Since the fork build is signed with a BestROM key, an
F-Droid or GitHub install would be refused for a signature mismatch as well, so
**the OTA is the only update channel for this keyboard** (see "What this
costs"). The in-app updater is a dead end either way; it is also inert unless
the user opens the Updates settings screen.

## Permissions

The default keyboard sees every keystroke on the device, so its permission set
belongs in writing. From `aapt2 dump permissions` on the shipped APK:

| Permission | What wants it |
| --- | --- |
| `INTERNET`, `ACCESS_NETWORK_STATE` | the destinations above - updater, dictionaries, models, optional cloud AI |
| `RECORD_AUDIO`, `MODIFY_AUDIO_SETTINGS` | voice input (whisper.cpp on device) |
| `CAMERA`, `READ_MEDIA_IMAGES`, `READ_EXTERNAL_STORAGE` (maxSdk 32) | custom keyboard background image, and the image picker for it |
| `READ_CONTACTS` | suggesting contact names while typing |
| `READ_USER_DICTIONARY`, `WRITE_USER_DICTIONARY` | the personal dictionary, shared with the framework |
| `VIBRATE` | key press haptics |
| `SYSTEM_ALERT_WINDOW` | the resize/one-handed overlay |
| `RECEIVE_BOOT_COMPLETED` | the two receivers described above |
| `WAKE_LOCK`, `FOREGROUND_SERVICE` | WorkManager, i.e. plugin downloads |

All of them are runtime or special permissions: the app is not privileged, so
camera, microphone, contacts and images stay denied until the user grants them
in the feature that needs them, and a user who never opens voice input or a
custom background never grants them at all. `REQUEST_INSTALL_PACKAGES` is the
one it deliberately does **not** have; see [Variant](#variant).

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
