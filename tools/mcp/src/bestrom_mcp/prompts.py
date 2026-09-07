"""Prompt templates.

Each one is the project's real order of operations, with the gates named. They
exist so an agent reads the rules before acting rather than after failing.
"""

from __future__ import annotations

RELEASE_CHECKLIST = """Release a BestROM build, in the project's order.

1. env_check. Stop if it reports blockers: a build with no disk headroom dies
   two hours in, and a build already in flight means someone else is working.
2. repo_status and manifest_check. Every project in the publish set must be on
   the branch the manifest tracks, and the two manifest copies must be
   byte-identical. Note that vendor/bestrom is often checked out on a feature
   branch while the manifest tracks voltage-17.
3. build_start with dry_run=true first. Read the command and the log path back
   to the maintainer, then run it with dry_run=false.
4. build_status every few minutes. The build is done when the log carries
   "BUILD EXIT: 0". Any other value means build_errors, not a retry.
5. verify_image with write_marker=true. It writes "verify gate passed" only
   when every check passed, including the forbidden ones.
6. build_artifacts to record the package name, size and sha256.
7. release_prepare with the release notes, dry_run=true. Show the three drafts
   (SourceForge README, changelog entry, OTA catalog) to the maintainer.
8. Only after a human has read the drafts: release_publish with dry_run=false
   and confirm=true.

release_publish re-checks both anti-drift gates itself and refuses without
them: the marker must contain "verify gate passed", and the newest package on
disk must be the one the marker recorded. Nothing is pushed, uploaded or
published without an explicit confirm - the OTA catalog reaches every user's
Updater.
"""

CRASH_TRIAGE = """Turn a phone-side report into evidence before proposing a fix.

1. device_list first. It reports whether the tunnel port has a listener (adb is
   not run at all without one), which build the phone is on, and whether root
   is available.
2. This is a user build with no adb root. /data/tombstones and every root-gated
   dump come back empty. Empty output is NOT evidence that there were no
   crashes - say so explicitly rather than reporting "no crashes found".
3. device_capture kind="crashes" and kind="dropbox". Read the returned rollup
   ("process :: first exception line") and the tag histogram. Do not pull the
   raw logs into context; they are on disk behind
   bestrom://device-evidence/latest and you can name a file to read.
4. Correlate the failing process against the image: is that package even in
   installed-files.txt for the build the phone reports? A crash in something we
   removed means the phone is on an older build.
5. device_capture kind="avc" when the failure smells like SELinux. SELinux is
   enforcing and stays enforcing; setenforce 0 is not a diagnosis.
6. Only then propose a change, and say which file it belongs in.
"""

NEW_FEATURE_BRANCH = """Start a change correctly in a repo-managed tree.

1. repo_status for the project you are about to touch. Compare its branch
   against the manifest revision - vendor/bestrom is often on a feature branch
   such as bestrom-bootanimation while the manifest tracks voltage-17, and
   committing to the wrong one means the change never reaches a build.
2. Branch from the manifest revision, not from whatever is checked out.
3. Make the change. Keep it inside one project where you can.
4. commit_message_check on the message BEFORE committing. Subject
   "area: Sentence-case summary", 50/72, a blank second line, 1-6 body lines,
   no AI vocabulary, no emoji, no invented trailers.
5. changelog_add for anything a user would notice, under
   "Unreleased (next build)".
6. Stop there. Pushing is the publish chain's job, behind its own gates - a
   feature branch never pushes.
"""

BUILD_TRIAGE = """Diagnose a failed build without reading the log.

1. build_status for the "BUILD EXIT: N" line and the tail. N is the truth; the
   exit status of whatever launched the build is not.
2. build_errors for the deduplicated FAILED:/error: extract. Twelve lines is
   usually enough to name the module.
3. env_check for disk headroom and the ccache hit rate. A build that dies
   without a compiler error is usually ENOSPC.
4. Decide the cleanup level:
   - a compile error: fix it and rebuild, no clean at all;
   - the product configuration changed, e.g. a package was removed: installclean
     is required, or a stale staged file is packaged into the zip;
   - a full clean throws away ~141 GB of out/ and hours of work. It is almost
     never the answer. Say why before proposing it.
5. If the log says "timed out polling", another build held the soong lock.
   Retry once; do not clean.
"""
