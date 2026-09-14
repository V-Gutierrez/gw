# Releasing gw

A tag is not a release. `git push --tags` puts the tag on GitHub, but nothing appears on
`/releases` — and the repo keeps advertising the previous version as *Latest*. Both sides
must be done: **the tag** for the Homebrew formula to point at, and **the GitHub Release**
for the version to exist as something a human can find.

> Learned the hard way: v0.8.0 through v0.8.3 were tagged, hashed, poured into the formula
> and `brew upgrade`d — and `/releases` still said v0.7.0, because this step was never part
> of the ritual written down anywhere.

## Checklist

### 1. The version bump
- Bump `version` in `pyproject.toml`.
- Move the `CHANGELOG.md` entry from *Unreleased* to `## vX.Y.Z (YYYY-MM-DD)`.

### 2. Tag it
```bash
git tag vX.Y.Z
git push https-origin vX.Y.Z          # tags only — do not push the branch blindly
```
Annotated tags (`git tag -a`) are preferred; if one is signed, sign it.

### 3. Real sha256 of the archive the formula will fetch
Never hash a tarball you built locally. The formula fetches the **GitHub auto-generated
archive**, so hash the bytes GitHub actually serves:
```bash
curl -sL -o /tmp/gw-X.Y.Z.tar.gz https://github.com/v-gutierrez/gw/archive/refs/tags/vX.Y.Z.tar.gz
shasum -a 256 /tmp/gw-X.Y.Z.tar.gz
```
Confirm the URL resolves from the tag *before* hashing — a typo in the tag name yields an
HTML error page with a plausible-looking hash.

### 4. Formula, in **both** repos
`HomebrewFormula/gw.rb` lives in this repo *and* in the tap `V-Gutierrez/homebrew-gw`
(`HomebrewFormula/gw.rb`). Update `url`, `sha256`, and the `test do` assertion — the test
matches the version string and will silently keep passing on a stale number.

```bash
brew update && brew upgrade gw
brew info gw            # must show the new stable version
brew test gw            # the version assertion above
```

### 5. The GitHub Release — the step that gets forgotten
```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z — <one-line headline>" \
  --notes-file /tmp/gw-release-X.Y.Z.md \
  --latest                 # only on the newest; --latest=false on backfills
```

Notes in the style already used on the page: a one-line thesis, then `### Added` /
`### Changed` / `### Fixed` / `### Install`. Say **what broke and why**, not just what
changed — the three scope bugs of 2026-09-14 are the standard for this: each one gets its
cause written down.

Verify with `gh release list --limit 5`: the new version carries **Latest**.

### 6. Backfill
If a version was tagged without a release, create it now — the tag still points at the right
commit and `--notes-file` can be written from the CHANGELOG entry. Create oldest first with
`--latest=false`, then the newest with `--latest`.

## What this protects

- Someone reading the repo sees the current version. A tag-only release makes the project
  look a week stale when it is not.
- The formula's `test do` assertion is the only thing tying brew to a version number; it is
  edited by hand and fails open.
- The sha256 is only as good as the bytes it was taken from.
