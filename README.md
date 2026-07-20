PID Cat REPL
============

A fork of [JakeWharton/pidcat][5], which is itself an update to Jeff Sharkey's
excellent [logcat color script][1]. Both filter `adb logcat` down to the log
entries for a specific application package; this fork adds an interactive,
full-screen filter UI on top, turning `pidcat` into more of a REPL than a
one-shot stream.

During application development you often want to only display log messages
coming from your app. Unfortunately, because the process ID changes every time
you deploy to the phone it becomes a challenge to grep for the right thing.

This script solves that problem by filtering by application package. Supply the
target package as the sole argument to the python script and enjoy a more
convenient development process.

    pidcat com.oprah.bees.android

If you just want the original, non-interactive `pidcat`, use the upstream
[JakeWharton/pidcat][5] project or pass `--plain` here, see [Interactive
mode](#interactive-mode) below.


Here is an example of the output when running for the Google Plus app:

![Example screen](screen.png)


Interactive mode
-----------------

When both stdin and stdout are a terminal, `pidcat` opens a full-screen filter
UI instead of streaming: logs render above a bottom prompt line, and whatever
you type live-filters the scrollback to lines containing every typed word,
case-insensitively.

 * `Backspace` edits the query, `Ctrl-U` clears it.
 * `Ctrl-L` forces a redraw; the view also tracks terminal resizes.
 * `Ctrl-C` or `Ctrl-D` quits and restores your scrollback.

Pass `--plain` to get the original streaming output instead, e.g. for
`pidcat --plain com.oprah.bees.android | grep Foo`. Piped input or output
(`adb logcat | pidcat com.oprah.bees.android`, `pidcat ... | less`) always
uses plain streaming, since there is no terminal to draw the UI on.


Install
-------

Use [Homebrew][2]:

```shell
brew tap imcarlost/pidcat-repl
brew trust imcarlost/pidcat-repl
brew install pidcat-repl
```


Make sure that `adb` from the [Android SDK][3] is on your PATH. This script will
not work unless this is that case. That means, when you type `adb` and press
enter into your terminal something actually happens.

To include `adb` and other android tools on your path:

    export PATH=$PATH:<path to Android SDK>/platform-tools
    export PATH=$PATH:<path to Android SDK>/tools

Include these lines in your `.bashrc` or `.zshrc`.

*Note:* `<path to Android SDK>` should be absolute and not relative.

`pidcat` requires at least version 8.30 of `coreutils`. Ubuntu 20.04 LTS already ships
with it, for 18.04 and below, `coreutils` can be upgraded from the `focal` repo by running
the following:

```shell
sudo add-apt-repository 'deb http://archive.ubuntu.com/ubuntu focal main restricted universe multiverse'
sudo apt-get update
sudo apt-get -t focal install coreutils
```

 [1]: http://jsharkey.org/blog/2009/04/22/modifying-the-android-logcat-stream-for-full-color-debugging/
 [2]: http://brew.sh
 [3]: http://developer.android.com/sdk/
 [5]: https://github.com/JakeWharton/pidcat
