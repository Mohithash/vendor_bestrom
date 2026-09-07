#!/bin/bash
#
# SPDX-FileCopyrightText: BestROM
# SPDX-License-Identifier: Apache-2.0
#
# Fetches the prebuilt binaries that are too large to keep in git. Run it once
# after "repo sync" and before the first build; the build wrapper
# (build-bestrom-run.sh) runs it too, so a normal build never needs it by hand.
#
# It is idempotent: a file that is already present with the right size and
# sha256 is left alone and costs no network. A file that is missing or wrong is
# downloaded to a temporary name in the destination directory, checked, and
# only then moved into place, so an interrupted run never leaves a partial APK
# where the build would pick it up.
#
# GitHub release assets are also checked against GitHub's Sigstore-signed
# release attestation for the digest, which binds those exact bytes to that
# repository and tag. A non-200 from the attestations API is fatal; set
# BESTROM_SKIP_ATTESTATION=1 to build without network access to api.github.com.

set -u

readonly TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly TREE_ROOT="$(cd "${TOOLS_DIR}/../../.." && pwd)"

# name | destination relative to the tree root | url | sha256 | size in bytes
readonly PREBUILTS=(
"CromiteWebView|vendor/bestrom/prebuilt/CromiteWebView/CromiteWebView.apk|https://github.com/uazo/cromite/releases/download/v148.0.7778.168-cb3baf14f52eb4365d017f640f85310735c19b79/arm64_SystemWebView.apk|dd690edc7ba909bfc095e798457cb874ab2d6ff1f63b980ed67cae5d725a8d14|297580352"
)

TMP=""
cleanup() { [ -n "$TMP" ] && rm -f "$TMP"; TMP=""; }
trap 'cleanup' EXIT INT TERM

err() { echo "fetch-prebuilts: $*" >&2; }

file_sha256() {
    sha256sum "$1" 2>/dev/null | cut -d' ' -f1
}

file_size() {
    stat -c %s "$1" 2>/dev/null || echo 0
}

# Verify the release attestation for a GitHub release asset. Prints nothing on
# success, returns non-zero on anything but a 200.
check_attestation() {
    local url="$1" sha="$2" name="$3"
    local slug code api

    # https://github.com/<owner>/<repo>/releases/download/<tag>/<asset>
    slug="${url#https://github.com/}"
    case "$url" in
        https://github.com/*/releases/download/*) ;;
        *) return 0 ;;
    esac
    slug="${slug%%/releases/download/*}"

    if [ "${BESTROM_SKIP_ATTESTATION:-0}" = "1" ]; then
        echo "  ${name}: attestation check skipped (BESTROM_SKIP_ATTESTATION=1)"
        return 0
    fi

    api="https://api.github.com/repos/${slug}/attestations/sha256:${sha}"
    code="$(curl -s -o /dev/null -w '%{http_code}' -L --max-time 60 \
        -H 'Accept: application/vnd.github+json' "$api" 2>/dev/null)"
    if [ "$code" != "200" ]; then
        err "${name}: attestation check failed, ${api} returned HTTP ${code:-000}"
        err "${name}: the digest is not attested to ${slug}. Set BESTROM_SKIP_ATTESTATION=1"
        err "${name}: only if you already trust the bytes and cannot reach api.github.com."
        return 1
    fi
    echo "  ${name}: attested to ${slug} (HTTP 200)"
    return 0
}

fetch_one() {
    local name="$1" rel="$2" url="$3" want_sha="$4" want_size="$5"
    local dest="${TREE_ROOT}/${rel}" got_sha got_size

    if [ -f "$dest" ] && [ "$(file_size "$dest")" = "$want_size" ] &&
       [ "$(file_sha256 "$dest")" = "$want_sha" ]; then
        echo "  ${name}: present and verified"
        return 0
    fi
    if [ -f "$dest" ]; then
        err "${name}: ${rel} is present but does not match the recorded digest, refetching"
    fi

    mkdir -p "$(dirname "$dest")" || return 1
    # The temporary file sits next to the destination so the move is a rename
    # on the same filesystem, and cleanup() removes it on every failure path.
    TMP="$(mktemp "${dest}.XXXXXX")" || return 1

    echo "  ${name}: downloading $(basename "$url") (${want_size} bytes)"
    if ! curl -L --fail --retry 3 --retry-delay 5 --connect-timeout 30 \
            -o "$TMP" "$url"; then
        err "${name}: download failed: ${url}"
        cleanup
        return 1
    fi

    got_size="$(file_size "$TMP")"
    if [ "$got_size" != "$want_size" ]; then
        err "${name}: size mismatch: got ${got_size}, expected ${want_size}"
        cleanup
        return 1
    fi
    got_sha="$(file_sha256 "$TMP")"
    if [ "$got_sha" != "$want_sha" ]; then
        err "${name}: sha256 mismatch"
        err "${name}:   got      ${got_sha}"
        err "${name}:   expected ${want_sha}"
        cleanup
        return 1
    fi

    if ! check_attestation "$url" "$want_sha" "$name"; then
        cleanup
        return 1
    fi

    if ! mv -f "$TMP" "$dest"; then
        err "${name}: cannot move the download into ${rel}"
        cleanup
        return 1
    fi
    TMP=""
    chmod 644 "$dest"
    echo "  ${name}: fetched and verified"
    return 0
}

main() {
    local entry name rel url sha size failed=0

    if ! command -v curl >/dev/null 2>&1; then
        err "curl is not installed"
        return 1
    fi
    if ! command -v sha256sum >/dev/null 2>&1; then
        err "sha256sum is not installed"
        return 1
    fi

    echo "fetch-prebuilts: tree ${TREE_ROOT}"
    for entry in "${PREBUILTS[@]}"; do
        IFS='|' read -r name rel url sha size <<< "$entry"
        if ! fetch_one "$name" "$rel" "$url" "$sha" "$size"; then
            failed=$((failed + 1))
        fi
    done

    if [ "$failed" -ne 0 ]; then
        err "${failed} prebuilt(s) could not be fetched"
        return 1
    fi
    return 0
}

main "$@"
