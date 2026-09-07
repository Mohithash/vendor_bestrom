# Verify profiles

A profile is the BestROM image gate as data. `verify_image` loads
`profiles/<name>.toml`, runs every check against `out/target/product/peridot`,
and writes the literal line `verify gate passed` into the build marker only when
all of them pass. `release_publish` refuses without that line.

## The one hard rule

**Every profile must contain at least one check with `forbidden = true`**, or it
is rejected at load time.

A gate that only asserts "the thing we want is present" passes a broken image.
That is not hypothetical: an image once shipped with both the old camera and the
new one staged in `out/`, because the gate checked only that the new one had
arrived. Pair every "present" check with its "absent" opposite, and mark the
absent half `forbidden = true` so the intent is visible in the file.

## Structure

```toml
name = "peridot"
description = "one line, shown in the report"

[[check]]
id = "aperture-apk-absent"     # unique, kebab-case; used by the `checks` argument
kind = "installed_files_count" # one of the seven kinds below
description = "..."            # why this check exists, not what it greps
op = "eq"                      # eq ne ge gt le lt
expected = 0
forbidden = true               # this check asserts an absence
```

## Check kinds

| Kind | Reads | Keys |
|---|---|---|
| `installed_files_count` | `installed-files*.txt` in `out/` | `files` (glob), `pattern`, `ignore_case`, `exclude`, `op`, `expected` |
| `arsc_string_count` | `unzip -p <apk> resources.arsc \| strings` | `apk` (glob), `pattern`, `op`, `expected` |
| `aapt2_resource_count` | `prebuilts/sdk/tools/linux/bin/aapt2 dump resources <apk>` | `apk` (glob), `pattern`, `op`, `expected` |
| `sepolicy_grep` | any text file under `out/`, typically `*.cil` | `files` (glob), `pattern`, `and_pattern`, `op`, `expected` |
| `buildprop_value` | a `build.prop` under `out/` | `files` (glob), `key`, `op` (`eq`/`ne`), `expected` |
| `apk_mtime_after` | mtimes in `out/` | `apk` (glob), `reference` (glob), `tolerance_s` |
| `zip_size_delta` | the two newest `BestROM-*.zip` | `max_abs_mb` |

`pattern` is a Python regular expression matched per line. `and_pattern` is the
second stage of a two-grep check — `sepolicy_grep` counts lines matching both,
which is how the chain scripts expressed
`grep '(allow fsck_untrusted self (capability' | grep -c sys_admin`.

A glob resolves to the **installed** copy, not a packaging intermediate: a bare
`Freezer.apk` also matches
`obj/PACKAGING/target_files_intermediates/.../Freezer.apk`, which is re-copied
on every build and is therefore always fresh. `apk_mtime_after` against that one
could never fail. It now reads `system_ext/priv-app/Freezer/Freezer.apk`, so the
check fires when ninja did not rebuild the module — including when the module
legitimately did not change and the build simply ran more than `tolerance_s`
later. Widen `tolerance_s` rather than pointing the glob back at `obj/`.

`op` compares actual against expected: `eq`, `ne`, `ge`, `gt`, `le`, `lt`. For
`buildprop_value` only `eq` and `ne` make sense; `ne` on a property that is
absent passes, which is how "this property must not be fabricated" is written.

## What belongs here and what does not

Durable invariants belong in the profile. A one-off measurement for a single
release — reading an ELF `.dynsym` to confirm a symbol was hidden, say — stays in
that release's chain script; adding a check kind for a check that runs once is
not worth the surface area.

## Testing a profile

`verify_image` with `write_marker=false` is read-only, so run it as often as you
like. The evaluator itself is pure and takes injected readers, so
`tests/test_verify.py` exercises a profile with no `out/` tree, no `aapt2` and no
`unzip` on the path.
