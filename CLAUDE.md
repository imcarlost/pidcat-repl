# pidcat-repl

A fork of [JakeWharton/pidcat](https://github.com/JakeWharton/pidcat) that adds an
interactive, full-screen filter UI on top of the original package-filtered `adb logcat`
viewer.

## Layout

Everything lives in a single script, `pidcat.py`. There is no build step, no test suite,
and no dependencies beyond Python 3 and `adb` on the PATH.

- `stream(emit)` parses `adb logcat` output and hands each formatted block to a callback.
  Both output modes feed off it.
- `InteractiveUI` is the fork's addition: alternate-screen rendering, a bottom prompt line,
  and live filtering of the retained scrollback.
- `--plain` bypasses `InteractiveUI` and prints blocks as they arrive, which is the
  upstream behavior. Non-TTY stdin or stdout forces plain mode too.

Run it directly during development: `./pidcat.py com.example.app`.

## Homebrew distribution

This fork is distributed through a personal tap, **not** homebrew-core. Two repos are
involved:

- `imcarlost/pidcat-repl` (this repo) holds the source and the version tags.
- `imcarlost/homebrew-pidcat-repl` holds `Formula/pidcat-repl.rb`. Cloned locally at
  `../homebrew-pidcat-repl`.

The core formula named `pidcat` is upstream's, unrelated to this one. Homebrew derives the
formula class name from the filename, so `pidcat-repl.rb` must keep the class
`PidcatRepl`.

### Publishing a new version

The formula pins a tarball URL plus its sha256, so the version bump, the tag, and the
formula must all move together. Order matters: the sha256 can only be computed after the
tag is pushed, because it hashes GitHub's generated tarball.

1. Bump `__version__` in `pidcat.py` and promote the `Unreleased` heading in
   `CHANGELOG.md` to the new version with today's date.
2. Commit and push to `main`.
3. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. Compute the tarball hash:

   ```sh
   curl -sL https://github.com/imcarlost/pidcat-repl/archive/refs/tags/vX.Y.Z.tar.gz \
     | shasum -a 256
   ```

5. In `../homebrew-pidcat-repl/Formula/pidcat-repl.rb`, update both the `url` version and
   the `sha256`. Commit and push.

Keep `__version__` in sync with the tag. A mismatch is invisible until someone runs
`pidcat --version` and sees the old number.

If a tag has to be moved after it was pushed, the tarball hash changes with it, so the
formula's `sha256` must be recomputed and pushed again or installs fail checksum
verification.

### Installing and testing the tap

```sh
brew tap imcarlost/pidcat-repl
brew install pidcat-repl
```

Recent Homebrew versions refuse formulae from untrusted third-party taps. The install
fails with a `Refusing to load formula ... from untrusted tap` error until the tap is
trusted once per machine:

```sh
brew trust imcarlost/pidcat-repl
```

That is a local trust decision each user makes for themselves; there is no way to
pre-authorize the tap from the publishing side. Getting into homebrew-core instead is not
realistic for this fork, since core already carries upstream `pidcat` and forks rarely
meet its notability bar.

After pushing a formula change, `brew update` before reinstalling, or the tap clone under
`$(brew --repository)/Library/Taps/` will still be on the old commit.
