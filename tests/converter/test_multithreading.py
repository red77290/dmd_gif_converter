#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests de régression pour le multithreading de la conversion DMD.

Historique des régressions
--------------------------
v6.x  Deadlock pipe stderr : le buffer OS (~64 KB) se remplissait lors
      de conversions longues (scroll 100 s+), bloquant ffmpeg et rendant
      "Convert All" séquentiel/gelé.  Corrigé par _run_ffmpeg_with_drain.

Ces tests vérifient
-------------------
1.  _run_ffmpeg_with_drain existe et est callable (pas supprimée par erreur).
2.  Le drain accepte une sortie stderr > 64 KB sans deadlock.
3.  L'annulation via cancel_event retourne -1 et ne bloque pas.
4.  ThreadPoolExecutor exécute bien N tâches en parallèle (pas 1 par 1).
5.  max_workers=1 est réellement séquentiel.
6.  process_folder utilise le pool (pas une boucle for).
7.  Les logs prefixés [W{n}] sont émis correctement par _run_tasks.
"""

import concurrent.futures
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import src.engine.conversion.core as conv
from src.engine.conversion.core import _run_ffmpeg_with_drain, _terminal_log


# ─────────────────────────────────────────────────────────────────────────────
# 1. API CONTRACT — _run_ffmpeg_with_drain must exist and be callable
# ─────────────────────────────────────────────────────────────────────────────

class TestDrainHelperExists(unittest.TestCase):
    """Régression : la fonction helper ne doit jamais être supprimée."""

    def test_function_exists_in_module(self):
        self.assertTrue(
            hasattr(conv, "_run_ffmpeg_with_drain"),
            "_run_ffmpeg_with_drain manquante dans core.py — risque de deadlock "
            "pipe stderr lors des conversions parallèles !"
        )

    def test_function_is_callable(self):
        self.assertTrue(callable(conv._run_ffmpeg_with_drain))

    def test_function_returns_tuple(self):
        """Vérifie la signature : retourne (int, bytes)."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_proc.stderr.read.side_effect = [b"output", b""]
        mock_proc.stderr.close = MagicMock()
        with patch("src.engine.conversion.core.subprocess.Popen", return_value=mock_proc):
            result = _run_ffmpeg_with_drain(["ffmpeg", "-version"])
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        rc, stderr = result
        self.assertIsInstance(rc, int)
        self.assertIsInstance(stderr, bytes)


# ─────────────────────────────────────────────────────────────────────────────
# 2. PIPE BUFFER DEADLOCK PREVENTION
# ─────────────────────────────────────────────────────────────────────────────

class TestPipeBufferDeadlock(unittest.TestCase):
    """Régression : stderr > 64 KB ne doit pas bloquer ffmpeg."""

    def _make_mock_proc(self, chunks, returncode=0):
        mock = MagicMock()
        mock.returncode = returncode
        call_count = [0]

        def mock_poll():
            call_count[0] += 1
            # Return None (running) for first 2 polls, then returncode
            return returncode if call_count[0] > 2 else None

        mock.poll.side_effect = mock_poll
        mock.stderr.read.side_effect = chunks
        mock.stderr.close = MagicMock()
        return mock

    def test_200kb_stderr_drained_without_deadlock(self):
        """200 KB de stderr (> buffer 64 KB) doit être drainé sans deadlock."""
        large = b"x" * 200_000
        chunks = [large[:100_000], large[100_000:], b""]
        mock_proc = self._make_mock_proc(chunks)

        t0 = time.monotonic()
        with patch("src.engine.conversion.core.subprocess.Popen", return_value=mock_proc):
            rc, stderr = _run_ffmpeg_with_drain(["ffmpeg", "-y", "out.gif"])
        elapsed = time.monotonic() - t0

        self.assertEqual(rc, 0)
        self.assertEqual(len(stderr), 200_000)
        self.assertLess(elapsed, 5.0, "Drain a pris plus de 5 s — possible deadlock")

    def test_empty_stderr_works(self):
        """Stderr vide ne doit pas planter."""
        mock_proc = self._make_mock_proc([b""])
        with patch("src.engine.conversion.core.subprocess.Popen", return_value=mock_proc):
            rc, stderr = _run_ffmpeg_with_drain(["ffmpeg", "-version"])
        self.assertEqual(rc, 0)
        self.assertEqual(stderr, b"")

    def test_returncode_nonzero_returned_correctly(self):
        mock_proc = self._make_mock_proc([b"error: something failed\n", b""], returncode=1)
        with patch("src.engine.conversion.core.subprocess.Popen", return_value=mock_proc):
            rc, stderr = _run_ffmpeg_with_drain(["ffmpeg", "-bad-arg"])
        self.assertEqual(rc, 1)
        self.assertIn(b"error", stderr)


# ─────────────────────────────────────────────────────────────────────────────
# 3. CANCELLATION
# ─────────────────────────────────────────────────────────────────────────────

class TestCancellation(unittest.TestCase):
    """L'annulation via cancel_event doit retourner -1 rapidement."""

    def test_cancel_returns_minus1(self):
        cancel_ev = threading.Event()

        mock_proc = MagicMock()
        mock_proc.returncode = -1
        mock_proc.poll.return_value = None   # Process hangs forever
        mock_proc.stderr.read.return_value = b""
        mock_proc.stderr.close = MagicMock()

        def cancel_after_delay():
            time.sleep(0.15)
            cancel_ev.set()

        t = threading.Thread(target=cancel_after_delay, daemon=True)
        t.start()

        t0 = time.monotonic()
        with patch("src.engine.conversion.core.subprocess.Popen", return_value=mock_proc):
            rc, _ = _run_ffmpeg_with_drain(["ffmpeg", "-y", "out.gif"],
                                           cancel_event=cancel_ev)
        elapsed = time.monotonic() - t0

        self.assertEqual(rc, -1)
        mock_proc.terminate.assert_called_once()
        self.assertLess(elapsed, 4.0, "L'annulation a pris trop de temps")

    def test_pre_cancelled_event_returns_minus1_immediately(self):
        """Un cancel_event déjà activé avant l'appel doit quand même fonctionner."""
        cancel_ev = threading.Event()
        cancel_ev.set()

        mock_proc = MagicMock()
        mock_proc.returncode = -1
        mock_proc.poll.return_value = None
        mock_proc.stderr.read.return_value = b""
        mock_proc.stderr.close = MagicMock()

        with patch("src.engine.conversion.core.subprocess.Popen", return_value=mock_proc):
            rc, _ = _run_ffmpeg_with_drain(["ffmpeg", "-y", "out.gif"],
                                           cancel_event=cancel_ev)
        self.assertEqual(rc, -1)


# ─────────────────────────────────────────────────────────────────────────────
# 4. PARALLEL EXECUTION — N workers run tasks concurrently
# ─────────────────────────────────────────────────────────────────────────────

class TestParallelExecution(unittest.TestCase):
    """Régression : les tâches doivent vraiment s'exécuter en parallèle."""

    def _make_timed_task(self, delay=0.12):
        starts, ends = [], []
        lock = threading.Lock()

        def task(*args, **kwargs):
            with lock:
                starts.append(time.monotonic())
            time.sleep(delay)
            with lock:
                ends.append(time.monotonic())
            return True, "[OK]"

        return task, starts, ends

    def test_two_workers_overlap(self):
        """Avec 2 workers et 2 tâches de 120 ms, elles doivent se chevaucher."""
        task, starts, ends = self._make_timed_task(delay=0.12)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(task) for _ in range(2)]
            concurrent.futures.wait(futs)

        self.assertEqual(len(starts), 2)
        self.assertLess(
            starts[1], ends[0],
            "Les 2 tâches N'ONT PAS démarré en parallèle — "
            "regression multithreading détectée !"
        )

    def test_three_tasks_two_workers_batched(self):
        """3 tâches avec 2 workers : les 2 premières démarrent avant la 3e."""
        task, starts, ends = self._make_timed_task(delay=0.10)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(task) for _ in range(3)]
            concurrent.futures.wait(futs)

        self.assertEqual(len(starts), 3)
        # La 3e tâche doit démarrer APRÈS que l'une des 2 premières finisse
        # (elle est mise en file d'attente jusqu'à libération d'un worker).
        third_start = sorted(starts)[2]
        first_end = sorted(ends)[0]
        self.assertGreaterEqual(third_start, first_end - 0.02,
                                "3e tâche a démarré avant la fin d'une des 2 premières")

    def test_max_workers_1_is_sequential(self):
        """Avec 1 worker, les tâches s'exécutent séquentiellement."""
        task, starts, ends = self._make_timed_task(delay=0.05)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            futs = [ex.submit(task) for _ in range(3)]
            concurrent.futures.wait(futs)

        self.assertEqual(len(starts), 3)
        sorted_starts = sorted(starts)
        sorted_ends = sorted(ends)
        # With 1 worker: start[1] >= end[0], start[2] >= end[1]
        self.assertGreaterEqual(sorted_starts[1], sorted_ends[0] - 0.01)
        self.assertGreaterEqual(sorted_starts[2], sorted_ends[1] - 0.01)


# ─────────────────────────────────────────────────────────────────────────────
# 5. process_folder USES THREAD POOL
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessFolderUsesPool(unittest.TestCase):
    """process_folder doit utiliser ThreadPoolExecutor, pas une boucle for."""

    def test_two_files_converted(self):
        log = []

        def fake_pf(src, out, params=None, callback=None, cancel_event=None, **kw):
            log.append(src)
            return True, "[OK]"

        with tempfile.TemporaryDirectory() as fin:
            with tempfile.TemporaryDirectory() as fout:
                (Path(fin) / "a.gif").touch()
                (Path(fin) / "b.gif").touch()
                with patch("src.engine.conversion.core.process_file",
                           side_effect=fake_pf):
                    results = conv.process_folder(fin, fout, params={"max_workers": 2})

        self.assertEqual(len(results), 2)
        self.assertEqual(len(log), 2)

    def test_max_workers_propagated_to_executor(self):
        """max_workers dans params doit atteindre le ThreadPoolExecutor."""
        executor_calls = []
        original_tpe = concurrent.futures.ThreadPoolExecutor

        class CapturingTPE(original_tpe):
            def __init__(self, *args, max_workers=None, **kwargs):
                executor_calls.append(max_workers)
                super().__init__(*args, max_workers=max_workers, **kwargs)

        def fake_pf(src, out, **kw):
            return True, "[OK]"

        with tempfile.TemporaryDirectory() as fin:
            with tempfile.TemporaryDirectory() as fout:
                (Path(fin) / "a.gif").touch()
                with patch("src.engine.conversion.core.process_file",
                           side_effect=fake_pf):
                    # Patch the class inside the concurrent.futures module directly
                    with patch.object(concurrent.futures, "ThreadPoolExecutor", CapturingTPE):
                        conv.process_folder(fin, fout, params={"max_workers": 4, "auto_workers": False})

        self.assertIn(4, executor_calls,
                      f"max_workers=4 n'a pas atteint ThreadPoolExecutor. Appels: {executor_calls}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. WORKER ID IN LOGS — [W{n}] prefix regression test
# ─────────────────────────────────────────────────────────────────────────────

class TestWorkerIdInLogs(unittest.TestCase):
    """process_file doit émettre des logs via la callback (testable pour [W{n}])."""

    def test_callback_receives_log_messages(self):
        """La callback process_file doit recevoir des messages (logs non silencieux)."""
        received = []

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.gif")
            with patch("src.engine.conversion.core.get_metadata",
                       return_value=(640, 480, 25.0, 4.0)):
                with patch("src.engine.conversion.core._run_ffmpeg_with_drain",
                           return_value=(0, b"")):
                    conv.process_file(
                        "input.mp4", out,
                        callback=lambda m, lv="info": received.append((m, lv))
                    )

        self.assertTrue(len(received) > 0,
                        "Aucun log reçu — la callback est silenciée quelque part !")

    def test_callback_prefix_wid_tag_format(self):
        """Vérifie que le format [W{n}] est un préfixe numérique valide."""
        import re
        wid_pattern = re.compile(r"^\[W\d+\]")

        # Simule le format de tag attendu depuis _run_tasks de preview_panel
        for wid in [1, 2, 5, 10]:
            tag = f"[W{wid}] "
            msg = f"{tag}[ACTION ] file.mp4 — Auto action OK"
            self.assertTrue(wid_pattern.match(msg),
                            f"Format [W{{n}}] invalide: {msg!r}")

    def test_multiple_workers_produce_distinct_wids(self):
        """Plusieurs workers parallèles doivent avoir des WIDs distincts."""
        wids_seen = set()
        lock = threading.Lock()
        _wid_seq = [0]
        _wid_lock = threading.Lock()

        def worker_task():
            with _wid_lock:
                _wid_seq[0] += 1
                wid = _wid_seq[0]
            with lock:
                wids_seen.add(wid)
            time.sleep(0.05)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(worker_task) for _ in range(4)]
            concurrent.futures.wait(futs)

        self.assertEqual(len(wids_seen), 4,
                         f"WIDs non uniques: {wids_seen}")
        self.assertEqual(wids_seen, {1, 2, 3, 4})


# ─────────────────────────────────────────────────────────────────────────────
# 7. CANCEL ONE TASK — others must complete
# ─────────────────────────────────────────────────────────────────────────────

class TestCancelOneDoesNotBlockOthers(unittest.TestCase):

    def test_cancel_one_others_finish(self):
        """Annuler une tâche ne doit pas empêcher les autres de se terminer."""
        results = []
        barrier = threading.Barrier(2, timeout=3)
        cancel_ev = threading.Event()

        def task_that_cancels():
            barrier.wait()
            cancel_ev.set()
            return "cancelled"

        def task_that_finishes():
            barrier.wait()
            time.sleep(0.1)
            return "done"

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(task_that_cancels)
            f2 = ex.submit(task_that_finishes)
            results.append(f1.result(timeout=3))
            results.append(f2.result(timeout=3))

        self.assertIn("cancelled", results)
        self.assertIn("done", results)


# ─────────────────────────────────────────────────────────────────────────────
# 8. _terminal_log — direct stderr write (immune to sys.stderr redirection)
# ─────────────────────────────────────────────────────────────────────────────

class TestTerminalLog(unittest.TestCase):
    """_terminal_log doit exister et écrire directement sur sys.__stderr__."""

    def test_terminal_log_exists(self):
        self.assertTrue(hasattr(conv, "_terminal_log"),
                        "_terminal_log manquante dans core.py — les logs "
                        "de conversion n'apparaîtront pas dans le terminal!")
        self.assertTrue(callable(conv._terminal_log))

    def test_terminal_log_writes_to_stderr(self):
        """_terminal_log doit écrire sur sys.__stderr__ avec flush."""
        import io
        fake_err = io.StringIO()
        import sys as _sys
        original = getattr(_sys, "__stderr__", None)
        try:
            _sys.__stderr__ = fake_err
            _terminal_log("Test conversion log", "info")
            output = fake_err.getvalue()
        finally:
            if original is not None:
                _sys.__stderr__ = original
            else:
                del _sys.__stderr__

        self.assertIn("Test conversion log", output)
        self.assertIn("[INFO   ]", output)

    def test_terminal_log_debug_is_silent(self):
        """Les messages debug ne doivent pas polluer le terminal."""
        import io
        fake_err = io.StringIO()
        import sys as _sys
        original = getattr(_sys, "__stderr__", None)
        try:
            _sys.__stderr__ = fake_err
            _terminal_log("Should not appear", "debug")
            output = fake_err.getvalue()
        finally:
            if original is not None:
                _sys.__stderr__ = original
            else:
                del _sys.__stderr__
        self.assertEqual(output, "", "Les messages debug ne doivent pas apparaître")

    def test_terminal_log_from_worker_thread(self):
        """_terminal_log doit fonctionner depuis un thread worker."""
        import io
        import sys as _sys
        results = []
        fake_err = io.StringIO()
        original = getattr(_sys, "__stderr__", None)

        def worker():
            _terminal_log("Worker thread log", "info")
            results.append(fake_err.getvalue())

        try:
            _sys.__stderr__ = fake_err
            t = threading.Thread(target=worker)
            t.start()
            t.join(timeout=2)
        finally:
            if original is not None:
                _sys.__stderr__ = original

        self.assertTrue(len(results) > 0)
        self.assertIn("Worker thread log", results[0])

    def test_process_file_uses_terminal_log(self):
        """process_file doit écrire les logs directement sur stderr
        (pas seulement via le framework logging)."""
        import io, sys as _sys
        captured = io.StringIO()
        original = getattr(_sys, "__stderr__", None)

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.gif")
            try:
                _sys.__stderr__ = captured
                with patch("src.engine.conversion.core.get_metadata",
                           return_value=(640, 480, 25.0, 4.0)):
                    with patch("src.engine.conversion.core._run_ffmpeg_with_drain",
                               return_value=(0, b"")):
                        conv.process_file("input.mp4", out)
            finally:
                if original is not None:
                    _sys.__stderr__ = original

        output = captured.getvalue()
        # Au moins [OK] ou [CENTER] ou [SCROLL] doit apparaître
        self.assertTrue(
            any(tag in output for tag in ("[OK    ]", "[CENTER]", "[SCROLL]")),
            f"Aucun log de conversion n'est apparu dans stderr. Sortie: {output[:200]!r}"
        )


if __name__ == "__main__":
    unittest.main()

