"""Stop verified Linux descendants that escape a launcher's process group."""

from collections import deque
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import select
import signal
import sys
import time


def _identity(pid):
    directory = Path(f"/proc/{pid}")
    try:
        text = (directory / "stat").read_bytes()
        fields = text[text.rfind(b")") + 2 :].split()
        if fields[0] == b"Z":
            return None
        return int(fields[1]), fields[19], directory.stat().st_uid
    except FileNotFoundError:
        return None


def _snapshot(process, stack, handles):
    # A live or unreaped Popen child cannot have had its PID reused.
    if process.poll() is not None:
        return
    root = _identity(process.pid)
    if root is None or root[2] != os.getuid():
        return
    queue = deque([(process.pid, root)])
    seen = {process.pid}
    while queue:
        pid, parent = queue.popleft()
        if _identity(pid) != parent:
            continue
        try:
            threads = list(Path(f"/proc/{pid}/task").iterdir())
        except FileNotFoundError:
            continue
        if len(threads) > 2048:
            raise RuntimeError("owned thread snapshot exceeded 2048 entries")
        for thread in threads:
            try:
                children = (thread / "children").read_text(encoding="ascii").split()
            except FileNotFoundError:
                continue
            for value in children:
                child_pid = int(value)
                if child_pid in seen:
                    continue
                child = _identity(child_pid)
                if child is None or child[0] != pid or child[2] != os.getuid():
                    continue
                try:
                    descriptor = os.pidfd_open(child_pid)
                except ProcessLookupError:
                    continue
                stack.callback(os.close, descriptor)
                if _identity(child_pid) != child or _identity(pid) != parent:
                    continue
                handles.append(descriptor)
                seen.add(child_pid)
                if len(seen) > 2048:
                    raise RuntimeError("owned process snapshot exceeded 2048 entries")
                queue.append((child_pid, child))


def _terminate(handles):
    pending = set(handles)
    poller = select.poll()
    for descriptor in pending:
        poller.register(descriptor, select.POLLIN)
    for signum, timeout in ((signal.SIGTERM, 0.25), (signal.SIGKILL, 0.5)):
        for descriptor in pending:
            try:
                signal.pidfd_send_signal(descriptor, signum)
            except ProcessLookupError:
                pass
            except OSError as error:
                print(
                    f"Desktop: could not stop an owned descendant: {error}",
                    file=sys.stderr,
                )
        deadline = time.monotonic() + timeout
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            for descriptor, _ in poller.poll(max(1, int(remaining * 1000))):
                pending.discard(descriptor)
                poller.unregister(descriptor)
    if pending:
        print(
            f"Desktop: {len(pending)} owned descendants have unconfirmed shutdown.",
            file=sys.stderr,
        )


@contextmanager
def stop_owned_descendants(process):
    """Pin current descendant identities, then stop survivors after group cleanup.

    Inspect only this owned Popen's child tree. PID file descriptors keep later
    signals tied to those exact processes even after reparenting or PID reuse.
    No process arguments, environment, or unrelated process inventory is read.
    """
    with ExitStack() as stack:
        handles = []
        try:
            _snapshot(process, stack, handles)
        except (AttributeError, OSError, RuntimeError) as error:
            print(
                f"Desktop: descendant ownership snapshot is incomplete: {error}",
                file=sys.stderr,
            )
        try:
            yield
        finally:
            _terminate(handles)
