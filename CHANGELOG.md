Unreleased (next build)
=======================

WebView
  * The Cromite WebView is now built from BestROM's own fork of Cromite
    (github.com/Mohithash/cromite, branch bestrom-148, same 148.0.7778.168
    base) instead of taken from uazo's release. Two changes on top:
    - WebView keeps Chromium's dangling-pointer detector off, as upstream
      WebView does. Cromite enables it for every target; inside another
      app's process its verdict is a crash of that app, and on Android 17
      it fired whenever a page's renderer was replaced under the Vulkan
      renderer, so Via and the licence viewer in Settings died within
      seconds of browsing.
    - The pointer it complained about is cleared before the object goes
      away (the Vulkan draw functor kept a stale pointer to its context
      provider between OnContextDestroyed and OnDestroyed).
  * The APK is signed with a BestROM WebView key rather than Cromite's;
    the ROM fetches it from the fork's GitHub release, sha256-pinned.

Tooling
  * BestROM now ships an MCP server (vendor/bestrom/tools/mcp) so AI
    agents can sync, build, verify the image, capture device evidence
    and prepare a release through defined tools with the same gates the
    chain scripts carry.
  * AGENTS.md, CLAUDE.md and .mcp.json land at the tree root via repo
    copyfile from vendor/bestrom/tools. After one repo sync a client
    starts the server itself; it needs uv and Python 3.11 on the machine.

Look and feel
  * A monochrome, true-black system theme is the default. Material You
    generates its palette with chroma zero, and in dark mode the page and
    the lowest surface are pure black. The surface ramp above them stays
    stepped (0C / 10 / 17 / 1B) so Settings cards, dialogs and the volume
    panel still read as cards on a page.
  * "Pure black" under Settings > Display > Dark theme is on out of the
    box. It is the same switch as before and still turns everything back
    to the tonal dark greys.
  * Two fonts ship with the ROM, both SIL Open Font License 1.1 from
    Google Fonts: Space Grotesk for anything you read, and Doto - a
    dot-matrix face - for the lock screen and always-on clock. Space
    Grotesk is the default body and headline font; the font picker in
    Settings still overrides it, and the clock stays dot-matrix whichever
    font you pick.
  * No window blur anywhere: the shade, the app-launch transition and
    window backgrounds all draw flat. SurfaceFlinger no longer advertises
    background blur at all, which removes a full-screen downsample and
    upsample pass from every shade drag.
  * Quick settings tiles are full pills when they are on, matching the
    off state. Notification cards are a little tighter, 24dp instead of
    28dp.
  * The app drawer background is opaque instead of 60% translucent. It
    reads better on black and it is one less blended layer for the
    compositor.
  * Animation scales are untouched - still 1.0x.
  * Settings looks like BestROM now. The homepage opens with a BESTROM
    eyebrow carrying the ROM version, a large dot-matrix Settings title,
    a 52dp search pill, and a card for the phone itself that opens
    About phone.
  * Every row on that page is its own rounded card with a 6dp gap, and
    the coloured icon circles are gone. Each row shows the first letter
    of its own name in a thin outlined ring; the letter comes from the
    translated title, so it still works in Malayalam, Hindi, Arabic,
    Chinese and Russian.
  * Battery, Storage and Custom Tweaks show a value at the end of the
    row - charge, space used and the ROM version. All three were already
    being computed, so the page reads nothing new when it opens: no
    account, app or Wi-Fi lookup was added.
  * Sub-pages follow the same card language, and their titles use the
    ROM body font instead of the one the collapsing toolbar names.
  * The dark greys in Settings are deliberate: the hint, the row values
    and the glyph rings sit below the usual text contrast because that
    is what the design asks for. Light mode keeps the standard colours.
    The whole restyle sits behind two config bools, so a device overlay
    can turn it - or just the device card - back off.

Branding
  * The Updater's banner is BestROM's own mark instead of the gold
    VoltageOS wordmark, which also takes 3.5 MB out of the app.
  * The version numbers agree. The Updater's current-build chip and the
    About phone version row both read a BestROM property now, not the
    VoltageOS platform version: the chip shows 3.0 and About shows the
    full build id.
  * The status bar's ongoing-activity chip draws the BestROM dot-matrix
    mark, so the toggle that offers it no longer shows another ROM's
    logo.
  * Custom Tweaks no longer fetches a Play Integrity profile from
    VoltageOS's GitHub. The auto-updated pifsync source stays, so the
    feature is unchanged apart from where the profile comes from.

Camera
  * MiuiCamera is the camera again (com.android.camera, Xiaomi's port).
    Aperture is dropped - bestrom_peridot.mk keeps PRODUCT_NO_CAMERA := true
    and ApertureOverlayPeridot is not installed.
  * Both peridot-miuicamera projects are back in the manifest: the device
    add-on (peridot-dev, lineage-23.2) and the blobs (NoPrincessHere,
    sixteen-qpr2), with the device.mk inherit and the BoardConfig -include.
  * Fixed: photos taken with MiuiCamera did not appear in the gallery. The
    MediaStore row was inserted at capture time and left pending, and the JPEG
    was only written at the next camera launch, from the thumbnail. On A17 a
    platform-signed app targeting SDK 35 runs as platform_app_36, so every
    sepolicy rule the MiuiCamera add-on writes against the bare platform_app
    type was dead - including the one that lets the app hand the camera HAL its
    BGService callback. Without binder "transfer" that registration died and
    MIVI post-processing never reported back, so every shot timed out at 24 s.
  * Also fixed alongside it: the camera provider's denied read of the kgsl
    devfreq symlink, its denied set of the persist.vendor.aiie_* properties, a
    noisy QSPM HIDL probe, and the vendor camera/display/audio property and
    /proc/pressure reads MiuiCamera does at launch.

WebView
  * The system WebView is Cromite's SystemWebView build
    (com.android.webview 148.0.7778.168) instead of the AOSP Chromium
    prebuilt. It keeps the AOSP package name, so nothing else in the
    image changes; the AOSP module is dropped by the prebuilt's
    overrides.
  * Cromite's binary has no variations-seed, metrics-upload or
    component-updater endpoints in it, so the WebView services that
    would talk to Google do nothing. The same removal has a cost:
    WebView no longer receives CRLSet certificate-revocation updates
    between ROM releases.
  * The other cost, stated plainly because it is the trade being made:
    Cromite's WebView asset is four Chrome majors behind the prebuilt it
    replaces - 148.0.7778.168 from 2026-05-21 against 152.0.7977.64 -
    and that asset comes from a CI workflow that lags Cromite's own
    browser releases. Check for a newer one before every release; the
    procedure is in vendor/bestrom/prebuilt/CromiteWebView/README.md.
  * The APK's sha256 is the digest GitHub's signed release attestation
    binds to that tag of uazo/cromite, so the shipped bytes can be
    checked against something other than themselves. Its signer,
    CN=CromiteOrg, still cannot be - Cromite publishes no fingerprint.
  * /product grows about 33 MB for it. The 297 MB APK is not in git -
    GitHub refuses a file that size and Git LFS would spend the whole
    monthly bandwidth quota in three clones. It is downloaded by
    vendor/bestrom/tools/fetch-prebuilts.sh, which checks its size,
    sha256 and release attestation; the build wrapper runs that script
    and the build stops early if the APK is missing.

Keyboard
  * LeanType 4.2.0 (com.leanbitlab.leantype), LeanBit Lab's HeliBoard
    fork, replaces AOSP LatinIME.
  * The keyboard now opens at full size. Upstream defaults to 77% height
    and 15% side padding; BestROM builds it from a one-commit fork that
    defaults both to 100%. The Appearance sliders still work and anyone
    who has already moved either one keeps their setting.
  * Because that is a fork build, it is signed with the ROM key rather
    than LeanBit Lab's, so the keyboard updates by OTA only - an F-Droid
    or GitHub install is refused for a signature mismatch. Its own in-app
    updater cannot install anything on a system build either, by design.
  * LeanType is GPL-3.0. The source for the build that ships is
    github.com/Mohithash/LeanType branch bestrom-17 - upstream tag v4.2.0
    plus the one commit, which is also kept in the ROM tree at
    vendor/bestrom/prebuilt/LeanType/patches/.
  * LeanType publishes no locale-tagged subtypes, so with LatinIME gone
    the framework selects no keyboard at all. BestromPreinstaller now
    seeds the enabled and default input method from its boot receiver
    when nothing is selected, so the setup wizard has a keyboard; a
    keyboard the user chose is never overridden.
  * It brings its own spell checker, so the Settings spell-checker row
    stays populated.
  * The keyboard is not a privileged app and asks for camera,
    microphone, contacts and image access only where a feature needs
    them - voice input, a custom background, contact suggestions - so
    nothing is granted until the user uses that feature. Its optional
    cloud proofreading carries no API key and does nothing until a user
    pastes one of their own; the models, dictionaries and handwriting
    packs it can download are all started from a settings screen.
  * The keyboard is the largest line item in the size delta: 57 MB
    installed against LatinIME's 22 MB, because LatinIME's bulk was
    dictionary data and LeanType's is code that peridot AOT-compiles
    whole. Together with the WebView, /product grows about 69 MB.

Files
  * MiXplorer 6.71.15 (com.mixplorer) is preloaded alongside Via as a
    normal, removable user app, installed once on first boot from
    /product/etc/bestrom/preinstall. It is the author's own arm64 build,
    shipped unmodified and with his signature intact, as his terms for
    preinstalling it in a ROM require. Grant it All files access on first
    run; it asks for no camera, location, microphone or contacts
    permission. Archive formats past ZIP need his separate MiX Archive
    add-on, which is not bundled. Adds 5.3 MB to /product.
  * Both preloads are copied into the image byte for byte and are never
    re-signed, which is what MiXplorer's author requires. Release
    signing is told to skip /product/etc/bestrom/preinstall; without
    that flag a release-signed build stops on a missing key for them.
  * A preload that fails to install because the device is out of space,
    or because the first boot was cut short, is now retried on the next
    boot instead of being written off. One that fails for a reason a
    retry cannot fix is still only attempted once, and uninstalling a
    preload still keeps it uninstalled.


BestROM 3.0 for POCO F6 (peridot)
=================================

Release:   3.0-peridot-20260906-1056-OFFICIAL
Package:   BestROM-3.0-peridot-20260906-1056-OFFICIAL.zip (2766633969 bytes)
sha256:    480a955452fe343943dc8e38cf2d633517e7d9e8b519c0ff8cb4ab51d819f27c
Android:   17 (SDK 37), AOSP android-17.0.0_r1, VoltageOS 6.1 base
Kernel:    6.1.176 GKI (android14-6.1), Theettam 2.7 lts176 (unchanged)
Patch:     platform 2026-08-01, vendor 2026-06-01 (OS3.0.302.0.WNPMIXM blobs)
Previous:  2026-09-06-1029 (first official build)

Flashing
--------
Boot to recovery, then:

    adb sideload BestROM-3.0-peridot-20260906-1056-OFFICIAL.zip

Dirty flash over any earlier build. No wipe required. First boot after
flashing takes a few minutes longer while apps are compiled.


Changes since 2026-09-06-1029
-----------------------------
Custom Tweaks (Powerhub)
  * Specter added as a Play Integrity fingerprint source, and the keybox
    can be fetched online. (Maintainer commit e5b606d.)

Notes
  * Built from an interactive shell rather than the release wrapper, so
    ro.build.user reads android-build instead of bestrom. The stock
    POCO fingerprint spoof is unaffected. Everything else is identical
    to 1029.


Previous release
================

BestROM 3.0 for POCO F6 (peridot)
=================================

Release:   3.0-peridot-20260906-1028-OFFICIAL
Package:   BestROM-3.0-peridot-20260906-1029-OFFICIAL.zip (2766631716 bytes)
sha256:    f2ff19b86b0013ac253cdffe3c5db7f0cf8b3d82ebf91e762e5b434b0da827bc
Android:   17 (SDK 37), AOSP android-17.0.0_r1, VoltageOS 6.1 base
Kernel:    6.1.176 GKI (android14-6.1), Theettam 2.7 lts176 (unchanged)
Patch:     platform 2026-08-01, vendor 2026-06-01 (OS3.0.302.0.WNPMIXM blobs)
Previous:  2026-09-06-0921

Flashing
--------
Boot to recovery, then:

    adb sideload BestROM-3.0-peridot-20260906-1029-OFFICIAL.zip

Dirty flash over 0551, 0416 or any 2026-09-05 build is supported. No
wipe required. Kernel and modules are unchanged since 1622.


FIRST OFFICIAL BESTROM BUILD.

Changes since 2026-09-06-0921
-----------------------------
Official
  * Build type OFFICIAL. BestROM official builds are the maintainer's own,
    gated on the maintainer's build environment rather than VoltageOS's
    device list and GPG keyring; ro.bestrom.build.status=OFFICIAL, and
    the package name and About page say so.
  * The Updater checks Mohithash/bestrom_ota (branch 17) for updates and
    changelogs instead of VoltageOS's OTA repository; the blocked-update
    help link no longer points at the LineageOS wiki.

Smoothness (audited: refresh-rate policy, SurfaceFlinger/HWUI pacing,
power hints, scheduler tunables, app launch, transition config; each
change verified against the code that reads it and against the GuidixX,
PixelOS and LineageOS peridot trees)
  * The INTERACTION power hint is held for the whole gesture: every node
    had a 120-1000 ms Duration while libperfmgr issues the hint once per
    gesture, so frequency floors and scheduler boosts reverted 120 ms
    into a scroll, fling or transition. Now Duration 0 like the reference
    trees; sched_boost 2 (top-app/foreground) instead of 1; three little
    cores kept online during interaction; the GPU floor action raises
    the floor to 353 MHz for 150 ms instead of re-asserting the idle
    default.
  * WindowManager's high-performance transition hint is enabled again
    (a device overlay had disabled it): SurfaceFlinger early wake-ups
    and the max refresh rate for the whole app open/close and recents
    animation.
  * A touch holds the high refresh-rate vote for 1000 ms (was 200 ms),
    so a tap that starts a transition does not see the panel fall back
    mid-animation; HWUI asks for CPU headroom earlier
    (target_cpu_time_percent 10). Both GuidixX values.
  * Animation durations back to AOSP: a VoltageOS commit had halved
    config_shortAnimTime/mediumAnimTime/longAnimTime and the activity
    durations, which made dialogs, popups, fragment, rotation and IME
    animations abrupt. Animation scales are the stock 1.0x.
  * Dexopt: vendor/voltage no longer overrides the device's compiler
    filters (first-boot=speed, bg-dexopt=speed-profile now apply; first
    boot after flashing takes a few minutes longer, once).
  Battery: the held interaction boost and the longer touch timer cost
  some power while the screen is being touched; it is the configuration
  the reference trees ship on this SoC.

Carried from 0921 and 0911:
Fingerprint
  * Enrolment ring radius restored (config_udfpsEnrollProgressBar=90).

About
  * The build-status row reads 'Official by Sal'; tapping it opens
    https://github.com/Mohithash. The 'Platform base' row is removed
    (Build number carries the version).

Biometrics: VoltageOS's implementation, BestROM's name
  * Face unlock and fingerprint code are VoltageOS's own: our earlier
    rename and bind fix and the two SystemUI UDFPS guards from 0551 are
    reverted, VoltageOS's rebrand and its follow-up fixup are applied.
    On top of that the app is renamed to com.bestrom.faceunlock in one
    consistent step, including a jarjar rule that relocates the
    references inside the prebuilt vendor jar, which the earlier rename
    missed and which is why it crashed. Re-enrol face data.

Settings
  * Powerhub is now 'Custom Tweaks' with a rocket icon.

Browser
  * Via Browser 7.3.3 (mark.via.gp) is preloaded as a normal, removable
    user app: a new BestromPreinstaller installs it once on first boot
    from /product/etc/bestrom/preinstall, and an uninstall sticks. A
    Jellyfish package entry that referred to nothing is dropped.

Phone
  * Up to 10000 call log entries are kept per SIM (was 500).

Known issues
  * Not yet verified on device: face-unlock enrolment (now VoltageOS's
    implementation) and fingerprint enrolment. Play Integrity is
    unaffected.


Previous release
================

BestROM 3.0 for POCO F6 (peridot)
=================================

Release:   3.0-peridot-20260906-0920-UNOFFICIAL
Package:   BestROM-3.0-peridot-20260906-0921-UNOFFICIAL.zip (2766627201 bytes)
sha256:    2dad642a30f2358c4dee43fd49fb8b53bf0cc5ff85d7a8c5964cd48978b85ed4
Android:   17 (SDK 37), AOSP android-17.0.0_r1, VoltageOS 6.1 base
Kernel:    6.1.176 GKI (android14-6.1), Theettam 2.7 lts176 (unchanged)
Patch:     platform 2026-08-01, vendor 2026-06-01 (OS3.0.302.0.WNPMIXM blobs)
Previous:  2026-09-06-0911

Flashing
--------
Boot to recovery, then:

    adb sideload BestROM-3.0-peridot-20260906-0921-UNOFFICIAL.zip

Dirty flash over 0551, 0416 or any 2026-09-05 build is supported. No
wipe required. Kernel and modules are unchanged since 1622.


Changes since 2026-09-06-0911
-----------------------------
Fingerprint
  * Enrolment: the finger icon and progress ring were drawn away from the
    sensor because the device overlay had lost
    config_udfpsEnrollProgressBar (the enrol ring radius Settings uses to
    position them). Restored to 90 dp, as in the LineageOS, PixelOS and
    GuidixX peridot trees.

Carried from 0911 (first published build with these):

About
  * The build-status row reads 'Official by Sal'; tapping it opens
    https://github.com/Mohithash. The 'Platform base' row is removed
    (Build number carries the version).

Biometrics: VoltageOS's implementation, BestROM's name
  * Face unlock and fingerprint code are VoltageOS's own: our earlier
    rename and bind fix and the two SystemUI UDFPS guards from 0551 are
    reverted, VoltageOS's rebrand and its follow-up fixup are applied.
    On top of that the app is renamed to com.bestrom.faceunlock in one
    consistent step, including a jarjar rule that relocates the
    references inside the prebuilt vendor jar, which the earlier rename
    missed and which is why it crashed. Re-enrol face data.

Settings
  * Powerhub is now 'Custom Tweaks' with a rocket icon.

Browser
  * Via Browser 7.3.3 (mark.via.gp) is preloaded as a normal, removable
    user app: a new BestromPreinstaller installs it once on first boot
    from /product/etc/bestrom/preinstall, and an uninstall sticks. A
    Jellyfish package entry that referred to nothing is dropped.

Phone
  * Up to 10000 call log entries are kept per SIM (was 500).

Known issues
  * Not yet verified on device: face-unlock enrolment (now VoltageOS's
    implementation) and fingerprint enrolment. Play Integrity is
    unaffected.


Previous release
================

BestROM 3.0 for POCO F6 (peridot)
=================================

Release:   3.0-peridot-20260906-0910-UNOFFICIAL
Package:   BestROM-3.0-peridot-20260906-0911-UNOFFICIAL.zip (2766627593 bytes)
sha256:    088c5152e60ee7cb47ebfb1af3893e104502ec42831ce1d6f0b9bc6bae6cb097
Android:   17 (SDK 37), AOSP android-17.0.0_r1, VoltageOS 6.1 base
Kernel:    6.1.176 GKI (android14-6.1), Theettam 2.7 lts176 (unchanged)
Patch:     platform 2026-08-01, vendor 2026-06-01 (OS3.0.302.0.WNPMIXM blobs)
Previous:  2026-09-06-0854

Flashing
--------
Boot to recovery, then:

    adb sideload BestROM-3.0-peridot-20260906-0911-UNOFFICIAL.zip

Dirty flash over 0551, 0416 or any 2026-09-05 build is supported. No
wipe required. Kernel and modules are unchanged since 1622.


Changes since 2026-09-06-0854
-----------------------------
(0854 shipped the items below but with two defects: face unlock would
still crash because the prebuilt vendor jar looked up its raw resources
under the old package name, and the Custom Tweaks title did not apply.
Both are fixed here; 0854 is withdrawn.)

About
  * The build-status row reads 'Official by Sal'; tapping it opens
    https://github.com/Mohithash. The 'Platform base' row is removed
    (Build number carries the version).

Biometrics: VoltageOS's implementation, BestROM's name
  * Face unlock and fingerprint code are VoltageOS's own: our earlier
    rename and bind fix and the two SystemUI UDFPS guards from 0551 are
    reverted, VoltageOS's rebrand and its follow-up fixup are applied.
    On top of that the app is renamed to com.bestrom.faceunlock in one
    consistent step, including a jarjar rule that relocates the
    references inside the prebuilt vendor jar, which the earlier rename
    missed and which is why it crashed. Re-enrol face data.

Settings
  * Powerhub is now 'Custom Tweaks' with a rocket icon.

Browser
  * Via Browser 7.3.3 (mark.via.gp) is preloaded as a normal, removable
    user app: a new BestromPreinstaller installs it once on first boot
    from /product/etc/bestrom/preinstall, and an uninstall sticks. A
    Jellyfish package entry that referred to nothing is dropped.

Phone
  * Up to 10000 call log entries are kept per SIM (was 500).

Known issues
  * Not yet verified on device: face-unlock enrolment (now VoltageOS's
    implementation) and fingerprint enrolment. Play Integrity is
    unaffected.


Previous release
================

BestROM 3.0 for POCO F6 (peridot)
=================================

Release:   3.0-peridot-20260906-0853-UNOFFICIAL
Package:   BestROM-3.0-peridot-20260906-0854-UNOFFICIAL.zip (2766635024 bytes)
sha256:    5f3f2ebc98b8677a2de6b52bebe34a09aaf8dba01731bc06b394d3edb26d5471
Android:   17 (SDK 37), AOSP android-17.0.0_r1, VoltageOS 6.1 base
Kernel:    6.1.176 GKI (android14-6.1), Theettam 2.7 lts176 (unchanged)
Patch:     platform 2026-08-01, vendor 2026-06-01 (OS3.0.302.0.WNPMIXM blobs)
Previous:  2026-09-06-0551

Flashing
--------
Boot to recovery, then:

    adb sideload BestROM-3.0-peridot-20260906-0854-UNOFFICIAL.zip

Dirty flash over 0551, 0416 or any 2026-09-05 build is supported. No
wipe required. Kernel and modules are unchanged since 1622.


Changes since 2026-09-06-0551
-----------------------------
About
  * The build-status row reads 'Official by Sal'; tapping it opens
    https://github.com/Mohithash. The 'Platform base' row is removed
    (Build number carries the version).

Biometrics: VoltageOS's implementation, BestROM's name
  * Face unlock and fingerprint code are VoltageOS's own: our earlier
    rename and bind fix and the two SystemUI UDFPS guards from 0551 are
    reverted, VoltageOS's rebrand and its follow-up fixup are applied.
    On top of that the app is renamed to com.bestrom.faceunlock in one
    consistent step, including a jarjar rule that relocates the
    references inside the prebuilt vendor jar, which the earlier rename
    missed and which is why it crashed. Re-enrol face data.

Settings
  * Powerhub is now 'Custom Tweaks' with a rocket icon.

Browser
  * Via Browser 7.3.3 (mark.via.gp) is preloaded as a normal, removable
    user app: a new BestromPreinstaller installs it once on first boot
    from /product/etc/bestrom/preinstall, and an uninstall sticks. A
    Jellyfish package entry that referred to nothing is dropped.

Phone
  * Up to 10000 call log entries are kept per SIM (was 500).

Known issues
  * Not yet verified on device: face-unlock enrolment (now VoltageOS's
    implementation) and fingerprint enrolment. Play Integrity is
    unaffected.


Previous release
================

BestROM 3.0 for POCO F6 (peridot)
=================================

Release:   3.0-peridot-20260906-0549-UNOFFICIAL
Package:   BestROM-3.0-peridot-20260906-0551-UNOFFICIAL.zip (2763843342 bytes)
sha256:    558818f72794d588d40f4fd4b6c824e21907c9d776e6c8c77159431d613caca2
Android:   17 (SDK 37), AOSP android-17.0.0_r1, VoltageOS 6.1 base
Kernel:    6.1.176 GKI (android14-6.1), Theettam 2.7 lts176 (unchanged)
Patch:     platform 2026-08-01, vendor 2026-06-01 (OS3.0.302.0.WNPMIXM blobs)
Previous:  2026-09-06-0416

Flashing
--------
Boot to recovery, then:

    adb sideload BestROM-3.0-peridot-20260906-0551-UNOFFICIAL.zip

Dirty flash over 0416 or any 2026-09-05 build is supported. No wipe
required. Kernel and modules are unchanged since 1622.


Changes since 2026-09-06-0416
-----------------------------
Second search of other trees (upstream VoltageOS, GrapheneOS 17,
Evolution-X, YAAP, other peridot device trees). Functional fixes only;
stock UI is unchanged.

Face unlock (regression fix)
  * Face unlock could not start on any 2026-09-05 build: the app had
    been renamed to com.bestrom.faceunlock while the framework kept
    binding co.aospa.sense, and the app's privileged-permission
    allowlists were still keyed on the old package. The framework,
    SystemUI privacy exemption, the app's bind action and all three
    allowlists now agree on com.bestrom.faceunlock. Re-enrol if face
    unlock was set up before.

Google services (sandboxed GmsCore)
  * Google Password Manager and passkeys: GmsCore's credential provider
    is declared with a system-only intent action that CredentialManager
    accepts only from preinstalled providers; it is rewritten to the
    ordinary action at package parse time. (GrapheneOS)
  * Optional GMS packages that are genuinely installed are no longer
    reported to GmsCore as absent; the real lookup runs first and the
    pseudo-disabled stub is used only when the package is missing.
    (GrapheneOS)

SystemUI
  * The under-display fingerprint overlay no longer crashes SystemUI
    when it is hidden after the view was already detached by a finger-up,
    bouncer or display-state race. (Evolution-X)
  * UdfpsHelper checks the view is attached before updating its dim
    animator instead of throwing per frame. (YAAP)
  * GameSpace's stop-recording action now stops the active screen
    recording. (VoltageOS upstream)

Play Integrity
  * TrickyStore refreshes its target list at most once per 5 s on the
    attestation path instead of on every check. (Evolution-X)

Device
  * /mnt/vendor/persist/fingerprint is labelled for units with the jiiov
    fingerprint sensor. (LineageOS)

Checked and already present
  * RescueParty disabled, UFFD garbage collector, lazy RCU boot
    parameters, the game 60 Hz cap removal, app-zygote UID guards.

Known issues
  * Not yet verified on device: face unlock enrolment and Google
    Password Manager as a credential provider are the two things to try.
    Play Integrity is unaffected.


Previous release
================

BestROM 3.0 for POCO F6 (peridot)
=================================

Release:   3.0-peridot-20260906-0530-UNOFFICIAL
Package:   BestROM-3.0-peridot-20260906-0532-UNOFFICIAL.zip (2763838139 bytes)
sha256:    35c4df2d3339dc225a4ab8e523816b5d50cee420e1e3ee7841d293196e197c74
Android:   17 (SDK 37), AOSP android-17.0.0_r1, VoltageOS 6.1 base
Kernel:    6.1.176 GKI (android14-6.1), Theettam 2.7 lts176 (unchanged)
Patch:     platform 2026-08-01, vendor 2026-06-01 (OS3.0.302.0.WNPMIXM blobs)
Previous:  2026-09-06-0521

Flashing
--------
Boot to recovery, then:

    adb sideload BestROM-3.0-peridot-20260906-0532-UNOFFICIAL.zip

Dirty flash over 0521, 0416 or any 2026-09-05 build is supported. No wipe
required. Kernel and modules are unchanged since 1622.


Changes since 2026-09-06-0521
-----------------------------
Device tree only (stock UI).

Theme
  * values-night/colors.xml no longer forces background_device_default_dark
    to #000000. This was the last override of the old monochrome pass;
    0521 removed the un-qualified copies but missed the night-qualified
    one. Stock Material You dark background applies again.

Carried from 0521: Double-tap to wake toggle shown in Settings, and the
2-acquired-buffers test (revert to 3 if the before/after measurement
shows more dropped frames).

Known issues
  * Not yet verified on device. Play Integrity is unaffected.


Previous release
================

BestROM 3.0 for POCO F6 (peridot)
=================================

Release:   3.0-peridot-20260906-0519-UNOFFICIAL
Package:   BestROM-3.0-peridot-20260906-0521-UNOFFICIAL.zip (2763838151 bytes)
sha256:    790b2c4f992377b8c4b97081c6c289000d08d6d114d45c73186157dc8cdf0825
Android:   17 (SDK 37), AOSP android-17.0.0_r1, VoltageOS 6.1 base
Kernel:    6.1.176 GKI (android14-6.1), Theettam 2.7 lts176 (unchanged)
Patch:     platform 2026-08-01, vendor 2026-06-01 (OS3.0.302.0.WNPMIXM blobs)
Previous:  2026-09-06-0416

Flashing
--------
Boot to recovery, then:

    adb sideload BestROM-3.0-peridot-20260906-0521-UNOFFICIAL.zip

Dirty flash over 0416 or any 2026-09-05 build is supported. No wipe
required. Kernel and modules are unchanged since 1622.


Changes since 2026-09-06-0416
-----------------------------
Device tree only (stock UI).

Theme
  * The last two overrides of the old monochrome pass are gone from the
    framework overlay: background_device_default_dark (forced #000000)
    and config_defaultNotificationColor (grey). Stock Material You values
    apply again in dark mode and for notification accents.

Display
  * The stock Double-tap to wake toggle is shown in Settings > Display
    (config_supportDoubleTapWake). The feature was already enabled and
    supported; only the switch was hidden.
  * TEST: ro.surface_flinger.max_frame_buffer_acquired_buffers 3 -> 2
    (the AOSP default; 3 is the Qualcomm reference value). With 3, HWUI
    reports high-input-latency frames (triple buffered but on time) on
    10-45% of frames in the launcher, SystemUI and the shade. If the
    before/after measurement shows more dropped frames with 2, this
    goes back to 3 in the next build.

Known issues
  * Not yet verified on device. Play Integrity is unaffected.


Previous release
================

BestROM 3.0 for POCO F6 (peridot)
=================================

Release:   3.0-peridot-20260906-0414-UNOFFICIAL
Package:   BestROM-3.0-peridot-20260906-0416-UNOFFICIAL.zip (2763838299 bytes)
sha256:    210c773ff5ef47572654f75f57e12e282e3e0bae2558b2159623cf7d9e80cf91
Android:   17 (SDK 37), AOSP android-17.0.0_r1, VoltageOS 6.1 base
Kernel:    6.1.176 GKI (android14-6.1), Theettam 2.7 lts176 (unchanged)
Patch:     platform 2026-08-01, vendor 2026-06-01 (OS3.0.302.0.WNPMIXM blobs)
Previous:  2026-09-05-2110

Flashing
--------
Boot to recovery, then:

    adb sideload BestROM-3.0-peridot-20260906-0416-UNOFFICIAL.zip

Dirty flash over any 2026-09-05 build or 2026-08-27 is supported. No
wipe required. Kernel and modules are unchanged since 1622.


Changes since 2026-09-05-2110
-----------------------------
UI back to stock
  * The 2047 look is reverted: no forced true-black surfaces, the
    Material You style defaults to TONAL_SPOT again, window and shade
    blur are back on, themed icons are off by default, and the default
    Quick Settings set, status-bar icons and wallpaper are stock
    VoltageOS. Anything set in Wallpaper & style is untouched.
  * Kept from 2110: battery percentage in the status bar by default,
    and the 0.75x animation-scale seeds (first boot only).
  * Kept: the nine framework changes from 2007 (Play Integrity
    hardening, crash fixes, media and binder fixes). None of them is
    visual.

Third-audit fixes
  * TrickyStore's keybox revocation check runs only in
    com.google.android.gms and com.android.vending instead of every
    process that requests key attestation. Warn-only, unchanged.
  * The setup wizard no longer links https://lineageos.org/legal; it
    points at the project's repository.
  * vendor.prop no longer carries ro.surface_flinger.supports_background_blur;
    the system property is the only source.

Reviewed and kept
  * GmsCompat, GmsCompatConfig, GmsCompatLib are required: Play services
    run sandboxed through GmsCompat; no privileged Google apps ship.
  * FaceUnlock is a working feature; opt out with
    TARGET_FACE_UNLOCK_SUPPORTED := false.

Known issues
  * Not yet verified on device. Play Integrity is unaffected.


Previous release
================

BestROM 3.0 for POCO F6 (peridot)
=================================

Release:   3.0-peridot-20260905-2109-UNOFFICIAL
Package:   BestROM-3.0-peridot-20260905-2110-UNOFFICIAL.zip (2763843700 bytes)
sha256:    e521186945268495db2239ba5371d1b2bb67b72c51957927aedb043b27060430
Android:   17 (SDK 37), AOSP android-17.0.0_r1, VoltageOS 6.1 base
Kernel:    6.1.176 GKI (android14-6.1), Theettam 2.7 lts176 (unchanged)
Patch:     platform 2026-08-01, vendor 2026-06-01 (OS3.0.302.0.WNPMIXM blobs)
Previous:  2026-09-05-2047

Flashing
--------
Boot to recovery, then:

    adb sideload BestROM-3.0-peridot-20260905-2110-UNOFFICIAL.zip

Dirty flash over 2047, 2007, 1622 or 2026-08-27 is supported. No wipe
required. Kernel and modules are unchanged since 1622.


Changes since 2026-09-05-2047
-----------------------------
Defaults only; everything from 2047 is carried unchanged.

Status bar
  * Battery percentage is shown by default
    (config_defaultBatteryPercentageSetting). A user who has turned it
    off keeps that choice.

Animation
  * Window, transition and animator duration scales default to 0.75x.
    These are first-boot seeds: a fresh install gets them, an existing
    install keeps its current values. Set them in Developer options or
    with settings put global {window_animation,transition_animation,
    animator_duration}_scale 0.75.
  * SettingsProvider now seeds ANIMATOR_DURATION_SCALE
    (def_animator_duration_scale) alongside the window and transition
    scales; AOSP never seeded it, so a device could not ship a default.

Known issues
  * Not yet verified on device. Play Integrity is unaffected (no
    properties touched).


Previous release
================

BestROM 3.0 for POCO F6 (peridot)
=================================

Release:   3.0-peridot-20260905-2046-UNOFFICIAL
Package:   BestROM-3.0-peridot-20260905-2047-UNOFFICIAL.zip (2763843476 bytes)
sha256:    5b669151b6476dbcbe279b8a8102ed81441a4a779eccdc98876f81254fe21e41
Android:   17 (SDK 37), AOSP android-17.0.0_r1, VoltageOS 6.1 base
Kernel:    6.1.176 GKI (android14-6.1), Theettam 2.7 lts176 (unchanged)
Patch:     platform 2026-08-01, vendor 2026-06-01 (OS3.0.302.0.WNPMIXM blobs)
Previous:  2026-09-05-2007

Flashing
--------
Boot to recovery, then:

    adb sideload BestROM-3.0-peridot-20260905-2047-UNOFFICIAL.zip

Dirty flash over 2007, 1622 or 2026-08-27 is supported. No wipe required.
Kernel and modules are unchanged since 1622.


Changes since 2026-09-05-2007
-----------------------------
UI only. Kernel, blobs, HALs and the framework changes from 2007 are
carried unchanged.

Theme
  * True-black dark surfaces. When Material You generates the dynamic
    colour overlay, the dark variants of the surface roles are forced to
    black / near-black (background, surface and surface_container to
    #000000; container_lowest #080808, dim #0C0C0C, container_low
    #0F0F0F, container_high #171717, container_highest #1B1B1B, bright
    #212121). Light mode is untouched. Secure setting system_black_theme
    (default 1) turns it off; a change applies at the next overlay
    regeneration (wallpaper or dark-mode change, or reboot).
  * Monochrome accents by default. The Material You style defaults to
    MONOCHROMATIC instead of TONAL_SPOT, and the unknown-style and
    unparsable-setting fallbacks follow it, so a colourful wallpaper no
    longer seeds colour system-wide. The style picker in Wallpaper &
    style still overrides it per user.
  * Themed (monochrome) launcher icons are on by default.
  * Default wallpaper re-exported as pure #000000 at the panel's native
    1220x2712 (was 1080x2400).

Flat UI
  * No window or shade blur: TARGET_ENABLE_BLUR is off for peridot, which
    selects ro.custom.blur.enable=false, persist.sysui.disableBlur=true
    and ro.surface_flinger.supports_background_blur=0; app-launch blur
    and shade-expansion blur are off in the framework overlay.

SystemUI defaults
  * Quick Settings default set trimmed to internet, bt, flashlight, dnd,
    rotation, battery, screenrecord, airplane. Every other tile remains
    in the tile editor.
  * Alarm, Bluetooth and VPN indicators are hidden from the status bar
    by default (plus the stock rotate and headset exclusions).
  * The status-bar icon animation no longer vibrates.

Known issues
  * Not yet verified on device. Things to look at after flashing: dark
    surfaces are black (shade, Settings, launcher drawer), accents are
    grey, and the shade has no blur. If Play Integrity was passing on
    2007 it is unaffected; this build touches no properties that
    attestation reads.


Previous release
================

BestROM 3.0 for POCO F6 (peridot)
=================================

Release:   3.0-peridot-20260905-2006-UNOFFICIAL
Package:   BestROM-3.0-peridot-20260905-2007-UNOFFICIAL.zip (2763847713 bytes)
sha256:    b3723cf050953461c2f083d8024b58808901280d3a300e395cdf7276924d836f
Android:   17 (SDK 37), AOSP android-17.0.0_r1, VoltageOS 6.1 base
Kernel:    6.1.176 GKI (android14-6.1), Theettam 2.7 lts176 (unchanged)
Patch:     platform 2026-08-01, vendor 2026-06-01 (OS3.0.302.0.WNPMIXM blobs)
Previous:  2026-09-05-1622

Flashing
--------
Boot to recovery, then:

    adb sideload BestROM-3.0-peridot-20260905-2007-UNOFFICIAL.zip

Dirty flash over 1622 or 2026-08-27 is supported. No wipe required. The
kernel and modules are the same as 1622.


Changes since 2026-09-05-1622
-----------------------------
Framework and system code only; device tree, kernel and blobs unchanged.
All nine framework changes are cherry-picks from Project-PenguinOS
(celerity, Android 17 on the same Qualcomm 26Q2 base); original authors
are kept in the commit history.

Play Integrity / root hiding
  * Property spoofing now applies at the SystemProperties layer.
    SystemProperties.get/getInt/getLong/getBoolean and the Handle fast
    path consult the PIF spoof service per process, so a caller reading
    ro.build.fingerprint (or any spoofed key) directly no longer bypasses
    the Build.* field spoof. Build fields are written through JNI
    (SetStatic*Field) instead of reflection.
  * SDK_INT spoof reads its target from the PIF config (fallback 32) and
    is applied only to the DroidGuard process; SECURITY_PATCH is synced
    to the raw properties.
  * TrickyStore: keybox XML is validated structurally before parsing
    (must carry an ECDSA/RSA key block and a serial/DeviceID), and on a
    24 h cooldown a background thread checks the keybox cert serials
    against android.googleapis.com/attestation/status. Warn-only,
    fail-open: a revoked or suspended keybox is now logged instead of
    failing attestation silently.

Media
  * codec2: the C2IgbaBuffer sync-fence wait was hard-coded to 1/60 s;
    24/30 fps content could time out ("Waiting a sync fence failed 110")
    and drop frames. Timeout now scales for low frame rates. (QTI)
  * audioflinger: DuplicatingThread buffering deepened (overflow buffers
    10 -> 16, output-track buffer 3x -> 6x); fixes glitches when playing
    to two outputs at once (speaker + Bluetooth / wired).

Graphics and input
  * SurfaceFlinger keeps the expensive-rendering hint asserted across
    client-composition cache hits during blur instead of dropping the
    GPU boost on every reused frame.
  * InputDispatcher: an inconsistent hover-event stream from a synthesized
    or injected event was a LOG(FATAL) that aborted system_server (device
    reboot). Downgraded to a warning.
  * Binder: BINDER_VM_SIZE raised from 1 MB to 4 MB (fewer FAILED BINDER
    TRANSACTION on large parcels; virtual reservation only).

SystemUI
  * KeyguardStateController: showing/secure flags made volatile. Secure
    Quick Settings tiles read them off the main thread and a stale value
    could skip the unlock prompt.

Build system
  * The build/make fork pin in the manifest now carries the VoltageOS
    copyfile/linkfile children (Makefile, build/envsetup.sh, build/core,
    build/target, build/tools, CleanSpec.mk, buildspec.mk.default). The
    earlier pin dropped them, so a repo sync removed the links and the
    build could not source envsetup.
  * frameworks/av now lives on its own fork (Mohithash/frameworks_av,
    bestrom-a17) and is pinned in the manifest.

Not changed in this build
  * Device tree, kernel, vendor blobs, sepolicy and overlays are identical
    to 1622 (device tree b0f259e, the Redmi overlay package-name fix,
    only affects Redmi Turbo 3 units).

Known issues
  * The SystemProperties-layer spoof is the change to verify: check Play
    Integrity (device + basic) after flashing. Untested on device as of
    this build.
  * Earlier-boot crash history (vendor.dolby.media.c2 early-boot SIGSEGV,
    mediacodeclist_generator abort) is unchanged; not reproduced on 1622.


Previous release
================

BestROM 3.0 for POCO F6 (peridot)
=================================

Release:   3.0-peridot-20260905-1620-UNOFFICIAL
Package:   BestROM-3.0-peridot-20260905-1622-UNOFFICIAL.zip (2763831276 bytes)
sha256:    91e958a747888ce15e8909503e4f01decef81f616ac569b6465823d8053a90c2
Android:   17 (SDK 37), AOSP android-17.0.0_r1, VoltageOS 6.1 base
Kernel:    6.1.176 GKI (android14-6.1), Theettam 2.7 lts176
Patch:     platform 2026-08-01, vendor 2026-06-01 (OS3.0.302.0.WNPMIXM blobs)
Previous:  2026-08-27 (BestROM A17)

Flashing
--------
Boot to recovery, then:

    adb sideload BestROM-3.0-peridot-20260905-1622-UNOFFICIAL.zip

The package flashes boot and vendor_boot together; do not mix the kernel
from one build with the modules of another (vermagic must match). Dirty
flash over the 2026-08-27 build is supported. No wipe required.


Changes since 2026-08-27
------------------------

Kernel
  net: qrtr: raise QRTR_NS_MAX_LOOKUPS to 512. The 6.1.176 cap of 64
      starved the sensors HAL on the sm8635 vendor stack; system_server
      hit its watchdog and the device boot-looped.
  ci: stop forcing KSU_SUSFS_ENABLE_LOG into every SUSFS flavor.

HALs
  power: ship android.hardware.power-service (libperfmgr). Was missing
      from the image because of a typo in the package name.
  thermal: ship android.hardware.thermal-service.qti. Was missing.
  touch: vendor.lineage.touch -> vendor.bestrom.touch (AIDL v1 frozen,
      hash regenerated), implementation and VINTF updated.
  ir, power: binaries renamed from *.lineage to *.xiaomi; power HAL log
      tag follows.
  seccomp: allow lseek for atfwd and qesdk-secmanager. minijail killed
      both every 5 s.
  seccomp: drop _llseek and the duplicate getdents64 line from the
      codec2 and c2audio ext-arm64 policies. _llseek is a 32-bit
      syscall name; minijail on arm64 rejected the whole policy.
  servicemanager: hide bestrom* / vendor.bestrom.* services from
      untrusted apps, same filter as the lineage names.

SELinux
  Rename the Lineage SDK type identifiers to bestrom_* (hal_lineage_*,
      lineage_*_service). adbroot domain -> bestrom_adbctl; rules kept.
  Rename HAL binary and service names in file_contexts and
      service_contexts; drop the unshipped lineage.hardware.radio
      hwservice contexts.
  Strip secilc ";;* lm" and m4 "#line" source-path comments from the
      shipped .cil and *_contexts files. The precompiled policy and its
      hash gate files are not touched.
  peridot: label vendor.qti.qspmhal@1.0.so same_process_hal_file;
      allow platform apps to find and call IBGService (MiuiCamera);
      label the camera provider's IVirtualCameraRegistrar; make the
      mi_thermald property context a vendor.sys.thermal. prefix.
  Label /data/bestrom_updates and the com.bestrom.updater seapp entry.

System properties
  Retire ro.voltage.*, org.voltage.version and ro.modversion. The
      surviving values move to ro.bestrom.* (build.status,
      platform_release_or_codename, maintainer.gpg_key/uid) and
      org.bestrom.version. Readers updated: Settings, Updater, recovery,
      backuptool, releasetools, DisplayResolutionManager, bootanimation.
  ro.system.build.fingerprint now carries the same stock POCO value as
      the other fingerprints. It leaked the real android-17 build id and
      the "eng.<user>" build number.
  BUILD_NUMBER is set explicitly at build time.
  dalvik: 12 GB heap tier (heapgrowthlimit 384m; the 6 GB tier gave 256m).

Framework
  Known setup-wizard package is org.bestrom.setupwizard.
  Boot-jar package check allows vendor.bestrom.*.
  LatinIME is dexpreopted with the speed filter, like SystemUI and the
      launcher.

Apps
  SetupWizard: package org.lineageos.setupwizard -> org.bestrom.setupwizard,
      module VoltageSetupWizard -> BestromSetupWizard. BestROM mark.
  Updater: package com.voltage.updater -> com.bestrom.updater; download
      directory /data/bestrom_updates; reads ro.bestrom.device and
      org.bestrom.version.
  FaceUnlock: package com.voltageos.faceunlock -> com.bestrom.faceunlock.
      The framework binds by action, not package.
  Freezer: launcher icon; in-place empty state instead of a toast that
      died with the activity; confirm dialog for the add-apps picker;
      unused-app scan runs only in Doze maintenance windows.
  Settings: BestROM strings and labels; Android version page shows the
      dotted-B vector with no background (was a JPEG with a black square);
      reads ro.bestrom.*.
  Font overlays: org.voltage.theme.font.* -> org.bestrom.theme.font.*.
  MiuiCamera replaces Aperture. VoltageJump removed.

Theme and UI
  FrameworkOverlayPeridot no longer overrides
      background_device_default_light to #000000. Toasts, popups and the
      Settings bottom bar rendered black-on-black in the light theme. The
      dark override is kept.
  Boot animation: the device tree's canonical 1440x2560 animation is
      shipped again; the generated one is dropped.
  Recovery: dot-matrix RECOVERY / FASTBOOTD header, monochrome grey
      scheme in both modes, install spinner taken from the boot
      animation, dot-matrix error icon, title from ro.bestrom.version.
  Default wallpaper is pure black.


Known issues
------------
  Bootloader is unlocked and AVB is disabled; hardware attestation
      reports it. Play Integrity DEVICE and STRONG fail. Unchanged.
  Dolby codec2 blob (from pdx245): E-AC3 verified on this build
      (c2.dolby.eac3.decoder decodes, no crash, service stable); AC-4 not
      tested for lack of a sample. The early-boot SIGSEGV seen on the
      2026-08 build did not reproduce.
  init.qti.media.rc, xiaomi_modem_sh, xiaomi_modem_cust_sh referenced
      scripts that are not in the image (MIUI-only helpers; upstream dropped
      them). Verified harmless: the media variant is static and the RIL/IMS
      stack runs without them. The dead service stanzas are removed in the
      source tree (device tree 6c33596, blobs CP2A-bestrom) and land in the
      next build; on this build they only log a failed start at boot.
  LineageOS SDK namespace (org.lineageos.platform, lineage* binder
      service names) is unchanged.
  Glimpse, QtiTelephonyCompat, GmsCompat, CalyxOS and ProtonAOSP
      components keep their upstream package ids.
