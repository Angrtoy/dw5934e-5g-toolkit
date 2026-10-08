"""Offline fault-injection model for the C lifecycle contract.

This does not load libqmi or execute the C tool.  It makes the ordering
requirements executable and `test_static_paths.py` verifies that the actual C
contains the corresponding phase/inflight gates and callback-source finishes.
"""
from enum import Enum, auto
import unittest


class Flight(Enum):
    NONE = auto()
    OPEN = auto()
    ALLOCATE = auto()
    BIND = auto()
    WORK = auto()
    RELEASE = auto()
    CLOSE = auto()


class Machine:
    def __init__(self, capabilities=False, operation="status"):
        self.flight = Flight.OPEN
        self.capabilities = capabilities
        self.operation = operation
        self.stop = self.terminal = self.opened = self.client = False
        self.cleanup_started = self.operation_ok = self.release_attempts = 0
        self.close_attempts = 0
        self.cleanup_failed = False
        self.rc = 1

    def signal(self):
        self.stop = True
        self.maybe_cleanup()

    def maybe_cleanup(self):
        if self.cleanup_started or self.flight is not Flight.NONE:
            return
        self.cleanup_started = True
        if self.client and self.opened:
            self.flight = Flight.RELEASE
            self.release_attempts += 1
        elif self.opened:
            self.flight = Flight.CLOSE
            self.close_attempts += 1
        else:
            self.finish()

    def open_done(self, ok=True):
        assert self.flight is Flight.OPEN
        self.flight = Flight.NONE
        if not ok:
            self.terminal = True
            self.maybe_cleanup()
        else:
            self.opened = True
            if self.stop or self.terminal:
                self.maybe_cleanup()
            else:
                self.flight = Flight.ALLOCATE

    def allocate_done(self, ok=True):
        assert self.flight is Flight.ALLOCATE
        self.flight = Flight.NONE
        if not ok:
            self.terminal = True
            self.maybe_cleanup()
        else:
            self.client = True
            if self.stop or self.terminal:
                self.maybe_cleanup()
            else:
                self.flight = Flight.WORK if self.capabilities else Flight.BIND

    def bind_done(self, ok=True):
        assert self.flight is Flight.BIND
        self.flight = Flight.NONE  # consume command_full_finish before cleanup
        if not ok:
            self.terminal = True
        elif not (self.stop or self.terminal):
            self.flight = Flight.WORK
        self.maybe_cleanup()

    def work_done(self, ok=True):
        assert self.flight is Flight.WORK
        self.flight = Flight.NONE  # consume finish before cleanup
        if not ok:
            self.terminal = True
        elif not (self.stop or self.terminal):
            self.operation_ok = True
        self.maybe_cleanup()

    def release_done(self, ok=True):
        assert self.flight is Flight.RELEASE
        self.flight = Flight.NONE
        if not ok:
            self.cleanup_failed = self.terminal = True
        self.client = False
        self.flight = Flight.CLOSE
        self.close_attempts += 1

    def close_done(self, ok=True):
        assert self.flight is Flight.CLOSE
        self.flight = Flight.NONE
        if not ok:
            self.cleanup_failed = self.terminal = True
        self.finish()

    def finish(self):
        self.rc = 0 if self.operation_ok and not (self.stop or self.terminal or self.cleanup_failed) else 1

    def normal_success(self):
        self.open_done(); self.allocate_done(); self.bind_done(); self.work_done(); self.release_done(); self.close_done()


class LifecycleFaultTests(unittest.TestCase):
    def test_signal_at_open_success_closes_without_allocate(self):
        m = Machine(); m.signal(); self.assertFalse(m.cleanup_started)
        m.open_done(); self.assertEqual(m.flight, Flight.CLOSE); self.assertEqual(m.close_attempts, 1)
        m.close_done(); self.assertEqual(m.rc, 1)

    def test_signal_at_allocate_success_releases_cid_then_closes(self):
        m = Machine(); m.open_done(); m.signal(); m.allocate_done()
        self.assertEqual(m.flight, Flight.RELEASE); self.assertEqual(m.release_attempts, 1)
        m.release_done(); self.assertEqual(m.flight, Flight.CLOSE); m.close_done(); self.assertEqual(m.rc, 1)

    def test_signal_at_work_consumes_before_release_and_late_success_cannot_recover(self):
        m = Machine(); m.open_done(); m.allocate_done(); m.bind_done(); m.signal(); m.work_done(ok=True)
        self.assertFalse(m.operation_ok); self.assertEqual(m.flight, Flight.RELEASE)
        m.release_done(); m.close_done(); self.assertEqual(m.rc, 1)

    def test_release_failure_still_closes(self):
        m = Machine(); m.open_done(); m.allocate_done(); m.bind_done(); m.work_done(); m.release_done(ok=False)
        self.assertEqual(m.flight, Flight.CLOSE); self.assertEqual(m.close_attempts, 1)
        m.close_done(); self.assertEqual(m.rc, 1)

    def test_close_failure_is_nonzero(self):
        m = Machine(); m.open_done(); m.allocate_done(); m.bind_done(); m.work_done(); m.release_done(); m.close_done(ok=False)
        self.assertEqual(m.rc, 1)

    def test_repeated_signal_only_starts_one_cleanup(self):
        m = Machine(); m.open_done(); m.allocate_done(); m.bind_done(); m.signal(); m.signal(); m.work_done()
        self.assertEqual(m.release_attempts, 1); m.release_done(); m.signal()
        self.assertEqual(m.close_attempts, 1); m.close_done(); self.assertEqual(m.rc, 1)

    def test_normal_success_cleans_up_and_returns_zero(self):
        m = Machine(); m.normal_success()
        self.assertEqual((m.release_attempts, m.close_attempts, m.rc), (1, 1, 0))

    def test_business_failure_cleans_up_and_returns_nonzero(self):
        m = Machine(); m.open_done(); m.allocate_done(); m.bind_done(); m.work_done(ok=False)
        self.assertEqual(m.flight, Flight.RELEASE); m.release_done(); m.close_done()
        self.assertEqual(m.rc, 1)

    def test_non_capability_operation_binds_before_work(self):
        m = Machine(); m.open_done(); m.allocate_done()
        self.assertEqual(m.flight, Flight.BIND)
        m.bind_done(); self.assertEqual(m.flight, Flight.WORK)

    def test_capabilities_skips_bind(self):
        m = Machine(capabilities=True); m.open_done(); m.allocate_done()
        self.assertEqual(m.flight, Flight.WORK)

    def test_voice_domain_is_non_capability_and_binds_before_work(self):
        m = Machine(operation="voice-domain"); m.open_done(); m.allocate_done()
        self.assertEqual(m.flight, Flight.BIND)
        m.bind_done(); self.assertEqual(m.flight, Flight.WORK)

    def test_bind_protocol_failure_releases_then_closes(self):
        m = Machine(); m.open_done(); m.allocate_done(); m.bind_done(ok=False)
        self.assertTrue(m.terminal); self.assertEqual(m.flight, Flight.RELEASE)
        m.release_done(); m.close_done(); self.assertEqual(m.rc, 1)

    def test_signal_during_bind_never_starts_work_and_cleans_up(self):
        m = Machine(); m.open_done(); m.allocate_done(); m.signal()
        self.assertEqual(m.flight, Flight.BIND)
        m.bind_done(); self.assertEqual(m.flight, Flight.RELEASE)
        m.release_done(); m.close_done(); self.assertEqual(m.rc, 1)


class CombinedDialImmediateHangup:
    """Executable model of the C OP_DIAL_IMMEDIATE_HANGUP callback contract.

    It models only callbacks after the ordinary create/open/allocate/bind path:
    production source assertions separately tie these transitions to the exact
    libqmi calls, latches, and internal signal callback.  No device is opened.
    """
    MAX_END_ATTEMPTS = 2

    def __init__(self):
        self.critical = False
        self.dial_calls = 0
        self.end_calls = []
        self.end_attempts = 0
        self.dial_seen = self.end_seen = False
        self.owned_id = None
        self.cancelled = False
        self.ok = False
        self.failed = False

    def start(self):
        self.critical = True
        self.dial_calls += 1

    def signal(self):
        # Mirrors production on_signal(): signals in this window do not cancel.
        if not self.critical:
            self.cancelled = True

    def dial_done(self, call_id=None, ok=True):
        if self.dial_seen:
            return
        self.dial_seen = True
        if not ok:
            self.critical = False
            self.failed = True
            return
        self.owned_id = call_id
        self.start_end()

    def start_end(self):
        self.end_attempts += 1
        self.end_seen = False
        self.end_calls.append(self.owned_id)

    def end_done(self, returned_id=None, ok=True):
        if self.end_seen:
            return
        self.end_seen = True
        if ok and returned_id == self.owned_id:
            self.critical = False
            self.ok = True
        elif self.end_attempts < self.MAX_END_ATTEMPTS:
            self.start_end()
        else:
            self.critical = False
            self.failed = True


class CombinedDialImmediateHangupTests(unittest.TestCase):
    def test_success_is_one_dial_then_one_matching_end(self):
        m = CombinedDialImmediateHangup(); m.start(); m.dial_done(37); m.end_done(37)
        self.assertEqual((m.dial_calls, m.end_calls, m.ok, m.failed), (1, [37], True, False))

    def test_dial_protocol_error_48_sends_no_end(self):
        m = CombinedDialImmediateHangup(); m.start(); m.dial_done(ok=False)
        self.assertEqual((m.dial_calls, m.end_calls, m.failed), (1, [], True))

    def test_signals_before_response_after_modem_accept_and_during_end_do_not_cancel(self):
        m = CombinedDialImmediateHangup(); m.start()
        m.signal()  # Dial in flight, before callback
        m.dial_done(11); m.signal()  # accepted by modem, before/during End callback
        m.end_done(11)
        self.assertFalse(m.cancelled); self.assertTrue(m.ok); self.assertEqual(m.end_calls, [11])

    def test_end_failure_retries_same_proven_id_once_without_second_dial(self):
        m = CombinedDialImmediateHangup(); m.start(); m.dial_done(255)
        m.end_done(ok=False); m.end_done(255)
        self.assertEqual((m.dial_calls, m.end_calls, m.end_attempts, m.ok), (1, [255, 255], 2, True))

    def test_end_failure_after_bound_is_terminal_not_unknown_hangup(self):
        m = CombinedDialImmediateHangup(); m.start(); m.dial_done(9)
        m.end_done(ok=False); m.end_done(ok=False)
        self.assertEqual((m.dial_calls, m.end_calls, m.failed), (1, [9, 9], True))

    def test_duplicate_callbacks_never_issue_another_dial_or_end(self):
        m = CombinedDialImmediateHangup(); m.start(); m.dial_done(3); m.dial_done(4)
        m.end_done(3); m.end_done(3)
        self.assertEqual((m.dial_calls, m.end_calls, m.owned_id), (1, [3], 3))


if __name__ == "__main__":
    unittest.main(verbosity=2)
