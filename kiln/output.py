"""
kiln/output.py

Build progress reporter — three output modes:

  TTY     (default when stdout is a terminal)
          In-place ANSI status display. Fixed list of components printed
          once, status tags updated in-place as builds progress.
          Parallel builds visible simultaneously — multiple lines change.

  PLAIN   (auto-detected when stdout is not a terminal, or --no-tty)
          One line printed per completion event. No cursor manipulation.
          Pipe/redirect/CI friendly. Parallel builds still run.

  VERBOSE (--verbose)
          Forces single worker. Full build stdout/stderr streamed to
          terminal in real time. Status lines printed sequentially.
          For debugging a broken build or component bring-up.

Per-build log capture:
  Every build gets stdout.log, stderr.log, combined.log (timestamped).
  Captured regardless of output mode.
  Streamed to terminal in VERBOSE mode.
  Surfaced on error in TTY and PLAIN modes (last N lines).
  Written to .kiln/audit/<manifest_hash>/

Status tags (fixed 9-char width including brackets):
  [ PENDING ]  in queue, deps not yet satisfied
  [ WAITING ]  deps satisfied, waiting for weight headroom
  [  SOLO   ]  waiting for running_weight == 0 (oversized weight)
  [ FETCH   ]  git fetch in progress
  [ CONFIG  ]  configure phase
  [ BUILD   ]  build phase
  [  TEST   ]  test phase
  [ INSTALL ]  install phase
  [ PACKAGE ]  package + cache store phase
  [ PUBLISH ]  pushing to global cache (--publish only)
  [ CACHED  ]  cache hit, nothing to do
  [   OK    ]  completed successfully
  [  ERROR  ]  failed
  [ SKIPPED ]  dep failed, not attempted
"""

from __future__ import annotations

import io
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import IO

from pip._vendor.rich import status


# ---------------------------------------------------------------------------
# Status tags
# ---------------------------------------------------------------------------

class Status(Enum):
    PENDING  = auto()
    WAITING  = auto()
    SOLO     = auto()
    FETCH    = auto()
    CONFIG   = auto()
    BUILD    = auto()
    TEST     = auto()
    INSTALL  = auto()
    PACKAGE  = auto()
    PUBLISH  = auto()
    CACHED   = auto()
    OK       = auto()
    ERROR    = auto()
    SKIPPED  = auto()


# ANSI colour codes
_RESET  = "\033[0m"
_GREEN  = "\033[32m"
_RED    = "\033[31m"
_YELLOW = "\033[33m"
_DIM    = "\033[2m"
_BOLD   = "\033[1m"

_STATUS_DISPLAY: dict[Status, tuple[str, str]] = {
    # status          tag text    colour
    Status.PENDING:  ("PENDING",  _DIM),
    Status.WAITING:  ("WAITING",  _DIM),
    Status.SOLO:     (" SOLO  ",  _YELLOW),
    Status.FETCH:    (" FETCH ",  _YELLOW),
    Status.CONFIG:   ("CONFIG ",  _YELLOW),
    Status.BUILD:    (" BUILD ",  _YELLOW),
    Status.TEST:     (" TEST  ",  _YELLOW),
    Status.INSTALL:  ("INSTALL",  _YELLOW),
    Status.PACKAGE:  ("PACKAGE",  _YELLOW),
    Status.PUBLISH:  ("PUBLISH",  _YELLOW),
    Status.CACHED:   ("CACHED ",  _DIM),
    Status.OK:       ("  OK   ",  _GREEN),
    Status.ERROR:    (" ERROR ",  _RED),
    Status.SKIPPED:  ("SKIPPED",  _DIM),
}

_TERMINAL_STATUSES = {Status.OK, Status.ERROR, Status.SKIPPED, Status.CACHED}


def _format_tag(status: Status, colour: bool = True) -> str:
    text, clr = _STATUS_DISPLAY[status]
    if colour and sys.stdout.isatty():
        return f"[{clr}{text}{_RESET}]"
    return f"[{text}]"


def _format_elapsed(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# Per-build log capture
# ---------------------------------------------------------------------------

class BuildLog:
    """
    Captures stdout and stderr for one build, with timestamps on combined.log.
    Optionally echoes to a stream (used in VERBOSE mode).
    Written to audit_dir when the build completes.
    """

    def __init__(self, component_name: str, echo_to: IO[str] | None = None):
        self.component   = component_name
        self._echo_to    = echo_to
        self._lock       = threading.Lock()
        self._stdout     = io.StringIO()
        self._stderr     = io.StringIO()
        self._combined   = io.StringIO()
        self._start_time = time.monotonic()

    def write_stdout(self, line: str) -> None:
        ts = time.monotonic() - self._start_time
        with self._lock:
            self._stdout.write(line)
            self._combined.write(f"[{ts:9.3f}] {line}")
        if self._echo_to:
            self._echo_to.write(line)
            self._echo_to.flush()

    def write_stderr(self, line: str) -> None:
        ts = time.monotonic() - self._start_time
        with self._lock:
            self._stderr.write(line)
            self._combined.write(f"[{ts:9.3f}] {line}")
        if self._echo_to:
            self._echo_to.write(line)
            self._echo_to.flush()

    def tail(self, n: int = 20) -> str:
        """Last n lines of combined log — shown on error."""
        with self._lock:
            lines = self._combined.getvalue().splitlines()
        return "\n".join(lines[-n:])

    def write_to_dir(self, audit_dir: Path) -> None:
        """Flush captured logs to audit directory."""
        audit_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            (audit_dir / "stdout.log").write_text(
                self._stdout.getvalue(), encoding="utf-8"
            )
            (audit_dir / "stderr.log").write_text(
                self._stderr.getvalue(), encoding="utf-8"
            )
            (audit_dir / "combined.log").write_text(
                self._combined.getvalue(), encoding="utf-8"
            )


# ---------------------------------------------------------------------------
# Component row — state for one row in the display
# ---------------------------------------------------------------------------

@dataclass
class ComponentRow:
    name:         str
    version:      str
    build_weight: int
    manifest_hash: str = ""
    status:       Status = Status.PENDING
    start_time:   float | None = None
    end_time:     float | None = None
    log:          BuildLog | None = None

    def elapsed(self) -> float | None:
        if self.start_time is None:
            return None
        end = self.end_time or time.monotonic()
        return end - self.start_time

    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES


# ---------------------------------------------------------------------------
# Output mode
# ---------------------------------------------------------------------------

class OutputMode(Enum):
    TTY     = auto()
    PLAIN   = auto()
    VERBOSE = auto()


def detect_output_mode(verbose: bool, no_tty: bool) -> OutputMode:
    if verbose:
        return OutputMode.VERBOSE
    if no_tty or not sys.stdout.isatty():
        return OutputMode.PLAIN
    return OutputMode.TTY


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------

class Reporter:
    """
    Thread-safe build progress reporter.

    Usage:
        reporter = Reporter(mode=OutputMode.TTY)
        reporter.set_components(nodes)        # called once at start
        reporter.update("zlib", Status.BUILD)
        reporter.update("zlib", Status.OK)
        reporter.finish()
    """

    # Number of tail lines shown on error
    ERROR_TAIL_LINES = 30

    def __init__(
        self,
        mode:      OutputMode = OutputMode.TTY,
        audit_dir: Path | None = None,
        max_weight: int = 8,
    ):
        self._mode       = mode
        self._audit_dir  = audit_dir
        self._max_weight = max_weight
        self._lock       = threading.Lock()
        self._rows:  list[ComponentRow] = []
        self._index: dict[str, ComponentRow] = {}
        self._start_time = time.monotonic()
        self._header_printed = False

    # --- Setup ---

    def set_components(self, nodes: list) -> None:
        """
        Called once with the full topo-sorted DAG before any builds start.
        nodes: list of ComponentNode from dag.py
        """
        with self._lock:
            self._rows = []
            self._index = {}
            for node in nodes:
                status = Status.CACHED if node.cache_hit else Status.PENDING
                row = ComponentRow(
                    name          = node.name,
                    version       = node.version,
                    build_weight  = node.build_weight,
                    manifest_hash = node.manifest_hash,
                    status        = status,
                )
                self._rows.append(row)
                self._index[node.name] = row

            if self._mode == OutputMode.TTY:
                self._print_tty_initial()
            elif self._mode in (OutputMode.PLAIN, OutputMode.VERBOSE):
                self._print_header()

    def make_log(self, component_name: str) -> BuildLog:
        """
        Create and attach a BuildLog for a component.
        In VERBOSE mode the log echoes to stdout in real time.
        """
        echo = sys.stdout if self._mode == OutputMode.VERBOSE else None
        log  = BuildLog(component_name, echo_to=echo)
        with self._lock:
            if component_name in self._index:
                self._index[component_name].log = log
        return log

    # --- Status updates ---
    def _set_terminal_title(self, title: str) -> None:
        if sys.stdout.isatty():
            sys.stdout.write(f"\033]0;{title}\007")
            sys.stdout.flush()

    def update(self, component_name: str, status: Status) -> None:
        """Update the status of a component. Thread-safe."""
        with self._lock:
            row = self._index.get(component_name)
            if row is None:
                return

            prev = row.status
            row.status = status
            
            row.status = status

            # Update terminal title for active builds
            if status not in _TERMINAL_STATUSES and status not in (Status.PENDING, Status.WAITING):
                self._set_terminal_title(f"kiln: {component_name} [{status.name.lower()}]")
            elif status == Status.OK:
                self._set_terminal_title(f"kiln: {component_name} ✓")
            elif status == Status.ERROR:
                self._set_terminal_title(f"kiln: {component_name} ✗")

            # Track timing
            if status not in _TERMINAL_STATUSES and prev in (Status.PENDING, Status.WAITING):
                row.start_time = time.monotonic()
            if status in _TERMINAL_STATUSES and row.end_time is None:
                row.end_time = time.monotonic()
                if row.start_time is None:
                    row.start_time = row.end_time

            if self._mode == OutputMode.TTY:
                self._redraw_tty()
            else:
                # PLAIN and VERBOSE: only print on terminal states
                if status in _TERMINAL_STATUSES:
                    self._print_plain_line(row)

            # On error: dump log tail
            if status == Status.ERROR:
                self._print_error_detail(row)

    def finish(self) -> None:
        """Print final summary line."""
        self._set_terminal_title("kiln")
        elapsed = time.monotonic() - self._start_time
        ok      = sum(1 for r in self._rows if r.status == Status.OK)
        cached  = sum(1 for r in self._rows if r.status == Status.CACHED)
        errors  = sum(1 for r in self._rows if r.status == Status.ERROR)
        skipped = sum(1 for r in self._rows if r.status == Status.SKIPPED)

        with self._lock:
            if self._mode == OutputMode.TTY:
                self._redraw_tty()
                print()

            parts = []
            if ok:      parts.append(f"{_GREEN}{ok} built{_RESET}")
            if cached:  parts.append(f"{_DIM}{cached} cached{_RESET}")
            if errors:  parts.append(f"{_RED}{errors} failed{_RESET}")
            if skipped: parts.append(f"{_DIM}{skipped} skipped{_RESET}")

            summary = "  ".join(parts)
            print(f"\nDone in {_format_elapsed(elapsed)}  —  {summary}")

    def running_weight(self) -> int:
        """Current sum of build_weight for active (non-terminal, non-pending) builds."""
        active_statuses = {
            Status.FETCH, Status.CONFIG, Status.BUILD,
            Status.TEST, Status.INSTALL, Status.PACKAGE, Status.PUBLISH,
        }
        return sum(
            r.build_weight for r in self._rows
            if r.status in active_statuses
        )

    # --- TTY rendering ---

    def _print_tty_initial(self) -> None:
        """Print the fixed component list once. Subsequent updates redraw in-place."""
        self._print_header()
        for row in self._rows:
            print(self._format_row(row))
        self._tty_line_count = len(self._rows)

    def _redraw_tty(self) -> None:
        """Move cursor up and redraw all rows in-place."""
        if not hasattr(self, '_tty_line_count'):
            return
        # Move cursor up
        sys.stdout.write(f"\033[{self._tty_line_count}A")
        for row in self._rows:
            # Clear line and rewrite
            sys.stdout.write("\033[2K")
            sys.stdout.write(self._format_row(row) + "\n")
        sys.stdout.flush()

    def _print_header(self) -> None:
        if self._header_printed:
            return
        self._header_printed = True
        print(f"\nKiln  —  max_weight: {self._max_weight}\n")

    def _format_row(self, row: ComponentRow) -> str:
        tag      = _format_tag(row.status)
        name     = f"{row.name:<24}"
        version  = f"{row.version:<12}"
        weight   = f"weight:{row.build_weight}"

        elapsed_str = ""
        if row.status in _TERMINAL_STATUSES and row.elapsed() is not None:
            if row.status not in (Status.CACHED,):
                elapsed_str = f"  {_DIM}{_format_elapsed(row.elapsed())}{_RESET}"

        return f"  {tag}  {name}  {version}  {weight}{elapsed_str}"

    def _print_plain_line(self, row: ComponentRow) -> None:
        tag     = _format_tag(row.status, colour=sys.stdout.isatty())
        elapsed = ""
        if row.elapsed() is not None and row.status not in (Status.CACHED,):
            elapsed = f"  {_format_elapsed(row.elapsed())}"
        print(f"{tag}  {row.name:<24}  {row.version}{elapsed}")
        sys.stdout.flush()

    def _print_error_detail(self, row: ComponentRow) -> None:
        """Print the tail of the build log on error."""
        if row.log is None:
            return
        tail = row.log.tail(self.ERROR_TAIL_LINES)
        if not tail:
            return
        print(f"\n{_RED}--- {row.name} build log (last {self.ERROR_TAIL_LINES} lines) ---{_RESET}")
        print(tail)
        print(f"{_RED}--- end ---{_RESET}\n")
        if self._audit_dir:
            audit_path = self._audit_dir / row.manifest_hash
            row.log.write_to_dir(audit_path)
            print(f"{_DIM}Full log: {audit_path}/combined.log{_RESET}\n")