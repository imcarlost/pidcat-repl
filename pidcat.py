#!/usr/bin/env -S python3 -u

'''
Copyright 2009, The Android Open Source Project

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
'''

# Script to highlight adb logcat output for console
# Originally written by Jeff Sharkey, http://jsharkey.org/
# Piping detection and popen() added by other Android team members
# Package filtering and output improvements by Jake Wharton, http://jakewharton.com

import argparse
import codecs
import collections
import os
import select
import signal
import sys
import re
import subprocess
import threading
from subprocess import PIPE

__version__ = '2.3.0'

LOG_LEVELS = 'VDIWEF'
LOG_LEVELS_MAP = dict([(LOG_LEVELS[i], i) for i in range(len(LOG_LEVELS))])
parser = argparse.ArgumentParser(description='Filter logcat by package name')
parser.add_argument('package', nargs='*', help='Application package name(s)')
parser.add_argument('-w', '--tag-width', metavar='N', dest='tag_width', type=int, default=23, help='Width of log tag')
parser.add_argument('-l', '--min-level', dest='min_level', type=str, choices=LOG_LEVELS+LOG_LEVELS.lower(), default='V', help='Minimum level to be displayed')
parser.add_argument('--color-gc', dest='color_gc', action='store_true', help='Color garbage collection')
parser.add_argument('--always-display-tags', dest='always_tags', action='store_true',help='Always display the tag name')
parser.add_argument('--current', dest='current_app', action='store_true',help='Filter logcat by current running app')
parser.add_argument('-s', '--serial', dest='device_serial', help='Device serial number (adb -s option)')
parser.add_argument('-d', '--device', dest='use_device', action='store_true', help='Use first device for log input (adb -d option)')
parser.add_argument('-e', '--emulator', dest='use_emulator', action='store_true', help='Use first emulator for log input (adb -e option)')
parser.add_argument('-c', '--clear', dest='clear_logcat', action='store_true', help='Clear the entire log before running')
parser.add_argument('-t', '--tag', dest='tag', action='append', help='Filter output by specified tag(s)')
parser.add_argument('-i', '--ignore-tag', dest='ignored_tag', action='append', help='Filter output by ignoring specified tag(s)')
parser.add_argument('-v', '--version', action='version', version='%(prog)s ' + __version__, help='Print the version number and exit')
parser.add_argument('-a', '--all', dest='all', action='store_true', default=False, help='Print all log messages')
parser.add_argument('--plain', dest='plain', action='store_true', help='Plain streaming output, without the interactive filter UI')

args = parser.parse_args()
min_level = LOG_LEVELS_MAP[args.min_level.upper()]

package = args.package

base_adb_command = ['adb']
if args.device_serial:
  base_adb_command.extend(['-s', args.device_serial])
if args.use_device:
  base_adb_command.append('-d')
if args.use_emulator:
  base_adb_command.append('-e')

if args.current_app:
  system_dump_command = base_adb_command + ["shell", "dumpsys", "activity", "activities"]
  system_dump = subprocess.Popen(system_dump_command, stdout=PIPE, stderr=PIPE).communicate()[0]
  running_package_name = re.search(".*TaskRecord.*A[= ]([^ ^}]*)", str(system_dump)).group(1)
  package.append(running_package_name)

if len(package) == 0:
  args.all = True

# Store the names of packages for which to match all processes.
catchall_package = list(filter(lambda package: package.find(":") == -1, package))
# Store the name of processes to match exactly.
named_processes = list(filter(lambda package: package.find(":") != -1, package))
# Convert default process names from <package>: (cli notation) to <package> (android notation) in the exact names match group.
named_processes = list(map(lambda package: package if package.find(":") != len(package) - 1 else package[:-1], named_processes))

header_size = args.tag_width + 1 + 3 + 1 # space, level, space

stdout_isatty = sys.stdout.isatty()

width = -1
try:
  # Get the current terminal width
  import fcntl, termios, struct
  h, width = struct.unpack('hh', fcntl.ioctl(0, termios.TIOCGWINSZ, struct.pack('hh', 0, 0)))
except:
  pass

BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)

RESET = '\033[0m'

def termcolor(fg=None, bg=None):
  codes = []
  if fg is not None: codes.append('3%d' % fg)
  if bg is not None: codes.append('10%d' % bg)
  return '\033[%sm' % ';'.join(codes) if codes else ''

def colorize(message, fg=None, bg=None):
  return termcolor(fg, bg) + message + RESET if stdout_isatty else message

def indent_wrap(message):
  wrap_area = width - header_size
  # width == -1 means detection failed; a non-positive wrap area (very narrow or
  # unsized terminal) would make the loop below never advance, so skip wrapping.
  if width == -1 or wrap_area <= 0:
    return message
  message = message.replace('\t', '    ')
  messagebuf = ''
  current = 0
  while current < len(message):
    next = min(current + wrap_area, len(message))
    messagebuf += message[current:next]
    if next < len(message):
      messagebuf += '\n'
      messagebuf += ' ' * header_size
    current = next
  return messagebuf


LAST_USED = [RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN]
KNOWN_TAGS = {
  'dalvikvm': WHITE,
  'Process': WHITE,
  'ActivityManager': WHITE,
  'ActivityThread': WHITE,
  'AndroidRuntime': CYAN,
  'jdwp': WHITE,
  'StrictMode': WHITE,
  'DEBUG': YELLOW,
}

def allocate_color(tag):
  # this will allocate a unique format for the given tag
  # since we dont have very many colors, we always keep track of the LRU
  if tag not in KNOWN_TAGS:
    KNOWN_TAGS[tag] = LAST_USED[0]
  color = KNOWN_TAGS[tag]
  if color in LAST_USED:
    LAST_USED.remove(color)
    LAST_USED.append(color)
  return color


RULES = {
  # StrictMode policy violation; ~duration=319 ms: android.os.StrictMode$StrictModeDiskWriteViolation: policy=31 violation=1
  re.compile(r'^(StrictMode policy violation)(; ~duration=)(\d+ ms)')
    : r'%s\1%s\2%s\3%s' % (termcolor(RED), RESET, termcolor(YELLOW), RESET),
}

# Only enable GC coloring if the user opted-in
if args.color_gc:
  # GC_CONCURRENT freed 3617K, 29% free 20525K/28648K, paused 4ms+5ms, total 85ms
  key = re.compile(r'^(GC_(?:CONCURRENT|FOR_M?ALLOC|EXTERNAL_ALLOC|EXPLICIT) )(freed <?\d+.)(, \d+\% free \d+./\d+., )(paused \d+ms(?:\+\d+ms)?)')
  val = r'\1%s\2%s\3%s\4%s' % (termcolor(GREEN), RESET, termcolor(YELLOW), RESET)

  RULES[key] = val


TAGTYPES = {
  'V': colorize(' V ', fg=WHITE, bg=BLACK),
  'D': colorize(' D ', fg=BLACK, bg=BLUE),
  'I': colorize(' I ', fg=BLACK, bg=GREEN),
  'W': colorize(' W ', fg=BLACK, bg=YELLOW),
  'E': colorize(' E ', fg=BLACK, bg=RED),
  'F': colorize(' F ', fg=BLACK, bg=RED),
}

PID_LINE = re.compile(r'^\w+\s+(\w+)\s+\w+\s+\w+\s+\w+\s+\w+\s+\w+\s+\w\s([\w|\.|\/]+)$')
PID_START = re.compile(r'^.*: Start proc ([a-zA-Z0-9._:]+) for ([a-z]+ [^:]+): pid=(\d+) uid=(\d+) gids=(.*)$')
PID_START_5_1 = re.compile(r'^.*: Start proc (\d+):([a-zA-Z0-9._:]+)/[a-z0-9]+ for (.*)$')
PID_START_DALVIK = re.compile(r'^E/dalvikvm\(\s*(\d+)\): >>>>> ([a-zA-Z0-9._:]+) \[ userId:0 \| appId:(\d+) \]$')
PID_KILL  = re.compile(r'^Killing (\d+):([a-zA-Z0-9._:]+)/[^:]+: (.*)$')
PID_LEAVE = re.compile(r'^No longer want ([a-zA-Z0-9._:]+) \(pid (\d+)\): .*$')
PID_DEATH = re.compile(r'^Process ([a-zA-Z0-9._:]+) \(pid (\d+)\) has died.?$')
LOG_LINE  = re.compile(r'^([A-Z])/(.+?)\( *(\d+)\): (.*?)$')
BUG_LINE  = re.compile(r'.*nativeGetEnabledTags.*')
BACKTRACE_LINE = re.compile(r'^#(.*?)pc\s(.*?)$')

adb_command = base_adb_command[:]
adb_command.append('logcat')
adb_command.extend(['-v', 'brief'])

# Clear log before starting logcat
if args.clear_logcat:
  adb_clear_command = list(adb_command)
  adb_clear_command.append('-c')
  adb_clear = subprocess.Popen(adb_clear_command)

  while adb_clear.poll() is None:
    pass

# This is a ducktype of the subprocess.Popen object
class FakeStdinProcess():
  def __init__(self):
    self.stdout = sys.stdin.buffer
  def poll(self):
    return None

if sys.stdin.isatty():
  adb = subprocess.Popen(adb_command, stdin=PIPE, stdout=PIPE)
else:
  adb = FakeStdinProcess()
pids = set()
last_tag = None
app_pid = None

def match_packages(token):
  if len(package) == 0:
    return True
  if token in named_processes:
    return True
  index = token.find(':')
  return (token in catchall_package) if index == -1 else (token[:index] in catchall_package)

def parse_death(tag, message):
  if tag != 'ActivityManager':
    return None, None
  kill = PID_KILL.match(message)
  if kill:
    pid = kill.group(1)
    package_line = kill.group(2)
    if match_packages(package_line) and pid in pids:
      return pid, package_line
  leave = PID_LEAVE.match(message)
  if leave:
    pid = leave.group(2)
    package_line = leave.group(1)
    if match_packages(package_line) and pid in pids:
      return pid, package_line
  death = PID_DEATH.match(message)
  if death:
    pid = death.group(2)
    package_line = death.group(1)
    if match_packages(package_line) and pid in pids:
      return pid, package_line
  return None, None

def parse_start_proc(line):
  start = PID_START_5_1.match(line)
  if start is not None:
    line_pid, line_package, target = start.groups()
    return line_package, target, line_pid, '', ''
  start = PID_START.match(line)
  if start is not None:
    line_package, target, line_pid, line_uid, line_gids = start.groups()
    return line_package, target, line_pid, line_uid, line_gids
  start = PID_START_DALVIK.match(line)
  if start is not None:
    line_pid, line_package, line_uid = start.groups()
    return line_package, '', line_pid, line_uid, ''
  return None

def tag_in_tags_regex(tag, tags):
  return any(re.match(r'^' + t + r'$', tag) for t in map(str.strip, tags))

ps_command = base_adb_command + ['shell', 'ps']
ps_pid = subprocess.Popen(ps_command, stdin=PIPE, stdout=PIPE, stderr=PIPE)
while True:
  try:
    line = ps_pid.stdout.readline().decode('utf-8', 'replace').strip()
  except KeyboardInterrupt:
    break
  if len(line) == 0:
    break

  pid_match = PID_LINE.match(line)
  if pid_match is not None:
    pid = pid_match.group(1)
    proc = pid_match.group(2)
    if proc in catchall_package:
      seen_pids = True
      pids.add(pid)

def stream(emit):
  '''Parse adb output and hand each formatted block to emit(search_text, block).

  search_text is the block's plain, markup-free text, used by the interactive
  filter; block is the colorized output.
  '''
  global last_tag, app_pid

  while adb.poll() is None:
    try:
      line = adb.stdout.readline().decode('utf-8', 'replace').strip()
    except KeyboardInterrupt:
      break
    if len(line) == 0:
      break

    bug_line = BUG_LINE.match(line)
    if bug_line is not None:
      continue

    log_line = LOG_LINE.match(line)
    if log_line is None:
      continue

    level, tag, owner, message = log_line.groups()
    tag = tag.strip()
    start = parse_start_proc(line)
    if start:
      line_package, target, line_pid, line_uid, line_gids = start
      if match_packages(line_package):
        pids.add(line_pid)

        app_pid = line_pid

        linebuf  = '\n'
        linebuf += colorize(' ' * (header_size - 1), bg=WHITE)
        linebuf += indent_wrap(' Process %s created for %s\n' % (line_package, target))
        linebuf += colorize(' ' * (header_size - 1), bg=WHITE)
        linebuf += ' PID: %s   UID: %s   GIDs: %s' % (line_pid, line_uid, line_gids)
        linebuf += '\n'
        emit('Process %s created for %s PID: %s' % (line_package, target, line_pid), linebuf)
        last_tag = None # Ensure next log gets a tag printed

    dead_pid, dead_pname = parse_death(tag, message)
    if dead_pid:
      pids.remove(dead_pid)
      linebuf  = '\n'
      linebuf += colorize(' ' * (header_size - 1), bg=RED)
      linebuf += ' Process %s (PID: %s) ended' % (dead_pname, dead_pid)
      linebuf += '\n'
      emit('Process %s (PID: %s) ended' % (dead_pname, dead_pid), linebuf)
      last_tag = None # Ensure next log gets a tag printed

    # Make sure the backtrace is printed after a native crash
    if tag == 'DEBUG':
      bt_line = BACKTRACE_LINE.match(message.lstrip())
      if bt_line is not None:
        message = message.lstrip()
        owner = app_pid

    if not args.all and owner not in pids:
      continue
    if level in LOG_LEVELS_MAP and LOG_LEVELS_MAP[level] < min_level:
      continue
    if args.ignored_tag and tag_in_tags_regex(tag, args.ignored_tag):
      continue
    if args.tag and not tag_in_tags_regex(tag, args.tag):
      continue

    # Captured before color markup is added to the message.
    search_text = '%s %s %s' % (level, tag, message)

    linebuf = ''

    if args.tag_width > 0:
      # right-align tag title and allocate color if needed
      if tag != last_tag or args.always_tags:
        last_tag = tag
        color = allocate_color(tag)
        tag = tag[-args.tag_width:].rjust(args.tag_width)
        linebuf += colorize(tag, fg=color)
      else:
        linebuf += ' ' * args.tag_width
      linebuf += ' '

    # write out level colored edge
    if level in TAGTYPES:
      linebuf += TAGTYPES[level]
    else:
      linebuf += ' ' + level + ' '
    linebuf += ' '

    # format tag message using rules
    for matcher in RULES:
      replace = RULES[matcher]
      message = matcher.sub(replace, message)

    linebuf += indent_wrap(message)
    emit(search_text, linebuf)


class InteractiveUI:
  '''Full-screen filter UI: log lines render above a bottom prompt line, and the
  typed query live-filters the scrollback. Every whitespace-separated word must
  appear in a block's plain text (case-insensitive) for it to be shown.'''

  MAX_ENTRIES = 10000  # (search_text, block) pairs kept for re-filtering
  MAX_VISIBLE = 5000   # rendered lines kept for the current query

  def __init__(self):
    self.lock = threading.Lock()
    self.entries = collections.deque(maxlen=self.MAX_ENTRIES)  # (entry_id, search_lower, block)
    self.visible = []  # (entry_id, line_text)
    self.next_entry_id = 0
    self.query = ''
    self.status = ''
    self.resized = False
    self.scroll_offset = 0  # lines scrolled up from the tail; 0 == following the live tail
    self.render_start = 0   # index into self.visible of the top rendered line
    self.rows, self.cols = self._term_size()

  def _term_size(self):
    try:
      size = os.get_terminal_size(sys.stdout.fileno())
      rows, cols = size.lines, size.columns
    except OSError:
      rows, cols = 24, 80
    if rows < 5 or cols < 20:
      rows, cols = 24, 80
    return rows, cols

  def _matches(self, search_lower):
    return all(token in search_lower for token in self.query.lower().split())

  def _append_visible(self, entry_id, block):
    new_lines = [(entry_id, line) for line in block.split('\n')]
    self.visible.extend(new_lines)
    if self.scroll_offset > 0:
      # Keep whatever the user is currently looking at in place instead of
      # letting newly-arrived lines push it down and out of view.
      self.scroll_offset += len(new_lines)
    overflow = len(self.visible) - self.MAX_VISIBLE
    if overflow > 0:
      del self.visible[:overflow]
      self.scroll_offset = max(0, self.scroll_offset - overflow)

  def emit(self, search_text, block):
    with self.lock:
      entry_id = self.next_entry_id
      self.next_entry_id += 1
      search_lower = search_text.lower()
      self.entries.append((entry_id, search_lower, block))
      if self._matches(search_lower):
        self._append_visible(entry_id, block)
      self._render()

  def set_query(self, query):
    with self.lock:
      self.query = query
      self.visible = []
      self.scroll_offset = 0
      for entry_id, search_lower, block in self.entries:
        if self._matches(search_lower):
          self._append_visible(entry_id, block)
      self._render()

  def refresh(self):
    global width
    with self.lock:
      self.rows, self.cols = self._term_size()
      width = self.cols  # future indent_wrap calls track the new size
      self._render()

  def _render(self):
    log_rows = max(1, self.rows - 2)
    max_offset = max(0, len(self.visible) - log_rows)
    if self.scroll_offset > max_offset:
      self.scroll_offset = max_offset
    end = len(self.visible) - self.scroll_offset
    start = max(0, end - log_rows)
    self.render_start = start
    window = self.visible[start:end]
    out = ['\x1b[H']
    # Pad above so the log content hugs the prompt, like a terminal.
    for _ in range(log_rows - len(window)):
      out.append('\x1b[K\n')
    for _, line in window:
      out.append(line + '\x1b[K\n')
    if self.query:
      state = '%d matching lines of %d blocks' % (len(self.visible), len(self.entries))
    else:
      state = '%d blocks' % len(self.entries)
    if self.scroll_offset > 0:
      state += ' \xb7 scrolled (End to jump to latest)'
    if self.status:
      state += ' \xb7 ' + self.status
    separator = ' %s \xb7 type to filter \xb7 ctrl-u clear \xb7 click a line to unfilter \xb7 esc/ctrl-c quit' % state
    out.append('\x1b[2m' + separator[:max(0, self.cols - 1)] + '\x1b[0m\x1b[K\n')
    out.append('\x1b[36m❯\x1b[0m ' + self.query + '\x1b[K')
    sys.stdout.write(''.join(out))
    sys.stdout.flush()

  MOUSE_RE = re.compile(r'^\[<(\d+);(\d+);(\d+)([Mm])$')

  def _scroll(self, delta):
    with self.lock:
      log_rows = max(1, self.rows - 2)
      max_offset = max(0, len(self.visible) - log_rows)
      self.scroll_offset = max(0, min(max_offset, self.scroll_offset + delta))
      self._render()

  def _handle_click(self, row):
    with self.lock:
      log_rows = max(1, self.rows - 2)
      if row < 1 or row > log_rows:
        return
      idx = self.render_start + (row - 1)
      if idx < 0 or idx >= len(self.visible):
        return
      entry_id = self.visible[idx][0]
    self._jump_to_entry(entry_id)

  def _jump_to_entry(self, entry_id):
    '''Clears the filter, rebuilds the full unfiltered scrollback, and scrolls
    so the clicked entry is in view with a bit of context above it.'''
    with self.lock:
      self.query = ''
      self.visible = []
      self.scroll_offset = 0
      target_index = None
      for eid, _search_lower, block in self.entries:
        for line in block.split('\n'):
          if target_index is None and eid == entry_id:
            target_index = len(self.visible)
          self.visible.append((eid, line))
      overflow = len(self.visible) - self.MAX_VISIBLE
      if overflow > 0:
        del self.visible[:overflow]
        if target_index is not None:
          target_index -= overflow
      if target_index is not None and target_index >= 0:
        log_rows = max(1, self.rows - 2)
        max_offset = max(0, len(self.visible) - log_rows)
        desired_end = target_index + max(1, log_rows // 3)
        self.scroll_offset = max(0, min(max_offset, len(self.visible) - desired_end))
      self._render()

  def _handle_escape(self, seq):
    m = self.MOUSE_RE.match(seq)
    if m:
      button, _col, row, kind = m.groups()
      if kind != 'M':  # ignore button-release reports
        return
      button = int(button)
      if button == 0:  # left click
        self._handle_click(int(row))
      elif button == 64:  # wheel up
        self._scroll(3)
      elif button == 65:  # wheel down
        self._scroll(-3)
      return
    log_rows = max(1, self.rows - 2)
    if seq in ('[A', 'OA'):  # up
      self._scroll(1)
    elif seq in ('[B', 'OB'):  # down
      self._scroll(-1)
    elif seq == '[5~':  # page up
      self._scroll(log_rows)
    elif seq == '[6~':  # page down
      self._scroll(-log_rows)
    elif seq in ('[H', '[1~'):  # home
      self._scroll(10 ** 9)
    elif seq in ('[F', '[4~'):  # end
      self._scroll(-(10 ** 9))

  def _read_escape(self, pending, fd, decoder):
    '''Consumes the sequence following an ESC already pulled from `pending`.
    Returns (seq, rest_of_pending). seq is None for a standalone Escape
    keypress (nothing followed it within the grace window), '' when ESC was
    followed by something unrelated, or the sequence body (e.g. '[A')
    otherwise.'''
    if not pending:
      # Give a fast terminal-generated sequence (arrow keys, mouse reports)
      # a brief window to arrive before treating this as a lone Escape.
      if select.select([fd], [], [], 0.01)[0]:
        data = os.read(fd, 64)
        if data:
          pending = decoder.decode(data)
    if not pending:
      return None, pending
    introducer = pending[0]
    if introducer not in ('[', 'O'):
      return '', pending
    seq = introducer
    pending = pending[1:]
    while not (seq[-1].isalpha() or seq[-1] == '~'):
      if not pending:
        if select.select([fd], [], [], 0.01)[0]:
          data = os.read(fd, 64)
          if data:
            pending += decoder.decode(data)
            continue
        break
      seq += pending[0]
      pending = pending[1:]
    return seq, pending

  def run(self, reader_thread):
    fd = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd)
    decoder = codecs.getincrementaldecoder('utf-8')('replace')
    signal.signal(signal.SIGWINCH, lambda *_: setattr(self, 'resized', True))
    # Alt screen, no autowrap, mouse click/wheel reporting (SGR encoding).
    sys.stdout.write('\x1b[?1049h\x1b[?7l\x1b[2J\x1b[H\x1b[?1000h\x1b[?1006h')
    sys.stdout.flush()
    tty.setcbreak(fd)
    reader_thread.start()
    pending = ''  # decoded characters carried over between reads
    try:
      with self.lock:
        self._render()
      while True:
        if self.resized:
          self.resized = False
          self.refresh()
        if not reader_thread.is_alive() and not self.status:
          self.status = 'adb ended, scrollback still filterable'
          with self.lock:
            self._render()
        if not pending:
          if not select.select([fd], [], [], 0.2)[0]:
            continue
          data = os.read(fd, 64)
          if not data:
            break
          pending = decoder.decode(data)
          if not pending:
            continue
        ch, pending = pending[0], pending[1:]
        if ch in ('\x7f', '\x08'):  # backspace
          if self.query:
            self.set_query(self.query[:-1])
        elif ch == '\x15':  # ctrl-u
          if self.query:
            self.set_query('')
        elif ch == '\x04':  # ctrl-d
          return
        elif ch == '\x0c':  # ctrl-l
          self.refresh()
        elif ch == '\x1b':
          seq, pending = self._read_escape(pending, fd, decoder)
          if seq is None:  # standalone Escape keypress
            return
          if seq:
            self._handle_escape(seq)
        elif ch in ('\r', '\n', '\t'):
          pass
        elif ch >= ' ':
          self.set_query(self.query + ch)
    except KeyboardInterrupt:
      pass
    finally:
      termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
      sys.stdout.write('\x1b[?1006l\x1b[?1000l\x1b[?7h\x1b[?1049l')
      sys.stdout.flush()


interactive = sys.stdin.isatty() and stdout_isatty and not args.plain
if interactive:
  try:
    import termios
    import tty
  except ImportError:
    interactive = False  # not a POSIX terminal; stream like before

if interactive:
  ui = InteractiveUI()
  stream_thread = threading.Thread(target=stream, args=(ui.emit,), daemon=True)
  ui.run(stream_thread)
else:
  if hasattr(signal, 'SIGPIPE'):
    # Die quietly like other unix filters when the downstream reader closes,
    # e.g. `pidcat --plain <pkg> | head`.
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
  stream(lambda search_text, block: print(block))
