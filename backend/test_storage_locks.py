from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from backend.storage_locks import DATA_LOCK, data_file_lock


class DataFileLockTests(unittest.TestCase):
    def test_nested_same_root_and_exception_release(self):
        # A subprocess timeout makes a regression fail instead of hanging the suite.
        code = """
from pathlib import Path
import sys
from backend.storage_locks import DATA_LOCK, data_file_lock
root = Path(sys.argv[1])
with DATA_LOCK, data_file_lock(root):
    with data_file_lock(root / '.'):
        pass
    try:
        with data_file_lock(root):
            raise ValueError('injected')
    except ValueError:
        pass
with data_file_lock(root):
    with data_file_lock(root):
        print('released')
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-c", code, directory],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True, text=True, timeout=4,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "released")

    def test_another_thread_cannot_enter_held_root(self):
        attempted = threading.Event()
        entered = threading.Event()
        errors = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def other():
                attempted.set()
                try:
                    with DATA_LOCK, data_file_lock(root):
                        entered.set()
                except BaseException as error:
                    errors.append(error)

            with DATA_LOCK, data_file_lock(root):
                thread = threading.Thread(target=other, daemon=True)
                thread.start()
                self.assertTrue(attempted.wait(2))
                self.assertFalse(entered.wait(0.1))
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors, errors)
            self.assertTrue(entered.is_set())

    def test_another_process_cannot_enter_held_root(self):
        code = """
from pathlib import Path
import sys
from backend.storage_locks import data_file_lock
root = Path(sys.argv[1])
(root / 'attempting').write_text('ready')
with data_file_lock(root):
    print('entered')
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = None
            try:
                with DATA_LOCK, data_file_lock(root):
                    child = subprocess.Popen(
                        [sys.executable, "-c", code, directory],
                        cwd=Path(__file__).resolve().parents[1],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    )
                    deadline = time.monotonic() + 3
                    while not (root / "attempting").exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue((root / "attempting").exists())
                    with self.assertRaises(subprocess.TimeoutExpired):
                        child.communicate(timeout=0.1)
                output, error = child.communicate(timeout=4)
                self.assertEqual(child.returncode, 0, error)
                self.assertEqual(output.strip(), "entered")
            finally:
                if child is not None and child.poll() is None:
                    child.kill()
                    child.communicate(timeout=3)


if __name__ == "__main__":
    unittest.main()
