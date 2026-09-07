# prebuilt/preinstall

APKs that ship in the image but are **not** system apps. `config/branding.mk`
copies each one to `/product/etc/bestrom/preinstall/` with `PRODUCT_COPY_FILES`,
and on the first `BOOT_COMPLETED` `packages/apps/BestromPreinstaller` installs
it through `PackageInstaller` as an ordinary, fully removable user app. A user
uninstall sticks: the preinstaller writes a `done_<packageName>` marker in its
`preinstall_state` SharedPreferences and never reinstalls a package it has
already handled.

## Contents

| File | Package | Version | Upstream |
|---|---|---|---|
| `Via.apk` | `mark.via.gp` | 7.3.3 | https://viayoo.com |
| `MiXplorer.apk` | `com.mixplorer` | 6.71.15 (`B26090422`, arm64) | https://mixplorer.com |

### Via.apk

    4,258,542 bytes
    sha256                   245e02eb1106dfd4d97d27f5bb68e97a2db9fe543f72ab93dc6b587b0e2da4fd
    certificate DN           CN=Various Tu, L=广西, ST=广西, C=CN
    certificate SHA-256      3df7f89d3b8d1315f05710c914fccbcf3a4e24980afddccb8dcebde90836a390

### MiXplorer.apk

MiXplorer, Hootan Parsa's file manager. The arm64 split (peridot is
`arm64-v8a`); the universal APK is 8.3 MB for the same app.

    5,298,293 bytes
    sha256                   bc2627659872cfc9895155d129c03eb8ac2b3c112cbdbe7303feb718f10c83f0
    certificate DN           CN=MiXplorer.com, OU=Android Development,
                             O=MiProjects - Hootan Parsa, L=Tehran, C=IR,
                             EMAILADDRESS=MiXplorer@gmail.com
    certificate SHA-256      724eebd26a756e0762c255052e49709391baa21d17d98c34071e091f18b90063
    certificate SHA-1        ca76778f8596f10a4cea041f3b3cef77cde44dc3

The author distributes MiXplorer from his own Google Drive, linked from
mixplorer.com and from the XDA thread
(https://xdaforums.com/t/app-2-3-mixplorer-v6-x-released-fully-featured-file-manager.1523691/).
There is no F-Droid listing - the app is proprietary freeware, not open source.
The file here came from https://github.com/nOneCode4u/mixplorer-google-drive,
an automated mirror of that Drive.

Since the mirror publishes no checksums, the bytes were verified two ways
instead of trusted: the same certificate is on an APK downloaded directly from
the author's own domain over TLS (`https://mixplorer.com/beta/`), and the 6.71.12
universal APK is byte-identical between this Drive-sourced mirror and the
independent XDA-sourced mirror `driftywinds/mixplorer-releases`.

**Ship it byte for byte.** The author's terms permit exactly this use - "All
developers and companies are allowed to add MiXplorer and its free addons in
their ROMs as pre-installed apps" - with one restriction: "Sharing the modified
APK file and with different signature is not permitted." So this stays a plain
`PRODUCT_COPY_FILES` entry. Do not turn it into an `android_app_import` with a
`certificate:`, and do not repack, re-zipalign or re-sign it. `NOTICE` in this
directory carries the attribution for both apps, since `PRODUCT_COPY_FILES`
attaches no license metadata and neither app reaches the generated NOTICE.

That wording is **second-hand**. It was read at
https://gitlab.com/IzzyOnDroid/repo/-/issues/44, where the reporter quotes the
developer; the primary source (the XDA thread) and `mixplorer.com/legal/` both
refuse automated requests from this build host, and mixplorer.com publishes no
terms page. Before a public release, archive the XDA post that carries the
grant (archive.org snapshot or PDF, saved next to this file) or get a one-line
written OK to `MiXplorer@gmail.com` and record the date. Until one of those
exists the grant is credible, not verified, and this paragraph should keep
saying so.

Archive formats beyond ZIP (7z, RAR, TAR, ISO) need the separate free MiX
Archive add-on (`com.mixplorer.addon.archive`), which is not shipped; the same
mirror carries it and the author's grant covers it.

Notable permissions: `MANAGE_EXTERNAL_STORAGE` (All files access, a Settings
special access the user must grant), `REQUEST_INSTALL_PACKAGES` /
`REQUEST_DELETE_PACKAGES`, `QUERY_ALL_PACKAGES`, `SYSTEM_ALERT_WINDOW`,
`PACKAGE_USAGE_STATS`, `WRITE_SETTINGS` and `ACCESS_SUPERUSER`. It requests no
camera, location, microphone, contacts, phone-state or SMS permission. The
privacy policy (mixplorer.com/legal/privacy/) states no PII collection and no
analytics; all network use is user-initiated.

## Adding another

Two steps, no code change - `Preinstaller.findApks()` takes every `*.apk` in the
directory, and the package name comes from `getPackageArchiveInfo`, so the
filename is cosmetic:

1. Drop the APK here. Match the naming convention: `<AppName>.apk`.
2. Add it to the `PRODUCT_COPY_FILES` block in `config/branding.mk`.
3. Nothing else - **as long as release signing already skips this directory**
   (see below). It does today, for every APK in here, so a new one is covered.

No `PRODUCT_PACKAGES` entry, no `Android.bp`, no sepolicy, no privapp
allowlist. Two consequences worth knowing: the bytes are paid twice (once in
`/product`, once in the copy `PackageInstaller` writes into `/data`), and
because it is not a Soong module it gets no dexpreopt - it is compiled on first
boot like any user install.

There is no ordering guarantee between APKs (`File.listFiles()` order), and each
is handled in its own try/catch, so one bad APK never stops the batch. An
install that fails for a reason a retry cannot fix - wrong ABI, malformed or
conflicting APK - is marked done and not tried again; one that fails for lack
of space, or is cut short by a reboot, is retried on the next boot.

## Release signing

Every `sign_target_files_apks` run over a target-files zip that carries this
directory must be given

    --skip_apks_with_path_prefix PRODUCT/etc/bestrom/preinstall/

This is a hard requirement, not a tidiness flag, and it applies to `Via.apk`
today as much as to `MiXplorer.apk`:

* `GetApkFileInfo` (`build/make/tools/releasetools/sign_target_files_apks.py`)
  calls anything ending in `.apk` an APK, anywhere in the zip - there is no path
  restriction.
* `META/apkcerts.txt` is generated by `build/make/core/Makefile` from
  `$(PACKAGES)`, i.e. from Soong/Make **module names**. A `PRODUCT_COPY_FILES`
  entry is not a module, so it never appears there. (Checked: the current
  `bestrom_peridot-apkcerts.txt` has 4,928 entries and neither preload.)
* `CheckApkAndApexKeysAvailable` then asserts on every APK it has no key for, so
  the first `BESTROM_OFFICIAL` or OTA signing run fails outright with
  `No key specified for: MiXplorer.apk, Via.apk`.

The skip prefix takes both out of that check and copies them into the signed
target-files byte for byte, which is what MiXplorer's terms require anyway.
`-e MiXplorer.apk= -e Via.apk=` (empty value = do not sign) has the same effect
for those two files; the prefix is preferred because it keeps covering the next
APK added here.

**Do not resolve the assertion by giving these APKs a key.** Signing MiXplorer
with the release key is precisely the "different signature" its author forbids.
Converting it to `android_app_import { presigned: true }` to earn an apkcerts
line is also wrong for a second reason: that installs it into `/product/app` as
a non-removable system app and throws away the removable-preload design.
