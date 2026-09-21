"""Tests for runtime.delivery.model state machine + error classes (§8.2/§8.3)."""

import random

import pytest

from runtime.delivery.model import (
    ErrorClass,
    JobStatus,
    RetryPolicy,
    TransitionError,
    can_transition,
    classify_error,
    is_unsent,
    next_attempt_at,
    transition,
)


def test_happy_path():
    s = JobStatus.PENDING
    s = transition(s, JobStatus.READY)
    s = transition(s, JobStatus.LEASED)
    s = transition(s, JobStatus.SENDING)
    s = transition(s, JobStatus.SUCCEEDED)
    assert s is JobStatus.SUCCEEDED


def test_approval_path():
    assert can_transition(JobStatus.PENDING, JobStatus.WAITING_APPROVAL)
    assert can_transition(JobStatus.WAITING_APPROVAL, JobStatus.READY)


def test_uncertain_never_retries_directly():
    assert not can_transition(JobStatus.UNCERTAIN, JobStatus.READY)
    assert not can_transition(JobStatus.UNCERTAIN, JobStatus.RETRY_WAIT)
    assert can_transition(JobStatus.UNCERTAIN, JobStatus.CONFIRMED_NOT_SENT)
    assert can_transition(JobStatus.CONFIRMED_NOT_SENT, JobStatus.READY)


def test_terminal_states_have_no_edges():
    for s in (JobStatus.SUCCEEDED, JobStatus.DEAD_LETTER, JobStatus.CANCELLED):
        with pytest.raises(TransitionError):
            transition(s, JobStatus.READY)


def test_illegal_edge_raises():
    with pytest.raises(TransitionError):
        transition(JobStatus.PENDING, JobStatus.SENDING)


def test_unsent_set():
    assert is_unsent(JobStatus.UNCERTAIN) and is_unsent(JobStatus.BLOCKED)
    assert not is_unsent(JobStatus.SUCCEEDED) and not is_unsent(JobStatus.MANUAL_REVIEW)


def test_classify_error_actions():
    assert classify_error(ErrorClass.FLOOD_WAIT, flood_wait_until=100.0).next_status is JobStatus.RETRY_WAIT
    assert classify_error(ErrorClass.FLOOD_WAIT, flood_wait_until=100.0).flood_wait_until == 100.0
    assert classify_error(ErrorClass.TRANSIENT).retryable
    u = classify_error(ErrorClass.RESULT_UNKNOWN)
    assert u.next_status is JobStatus.UNCERTAIN and not u.retryable
    assert classify_error(ErrorClass.AUTH_DEAD).worker_halts
    assert classify_error(ErrorClass.STORAGE_DOWN).worker_halts
    assert classify_error(ErrorClass.PERMISSION_BLOCKED).next_status is JobStatus.BLOCKED
    assert classify_error(ErrorClass.CONTENT_INVALID).next_status is JobStatus.FAILED_PERMANENT


def test_backoff_exponential_and_capped():
    pol = RetryPolicy(max_attempts=5, base_delay_s=10.0, max_delay_s=60.0, jitter=0.0)
    t1 = next_attempt_at(pol, 1, now=0.0)
    t2 = next_attempt_at(pol, 2, now=0.0)
    t3 = next_attempt_at(pol, 3, now=0.0)
    assert t1 == 10.0 and t2 == 20.0 and t3 == 40.0
    assert next_attempt_at(pol, 10, now=0.0) is None  # attempts exhausted -> dead letter
    pol_big = RetryPolicy(max_attempts=20, base_delay_s=10.0, max_delay_s=60.0, jitter=0.0)
    assert next_attempt_at(pol_big, 10, now=0.0) == 60.0  # capped


def test_backoff_jitter_bounds():
    pol = RetryPolicy(max_attempts=5, base_delay_s=100.0, jitter=0.5)
    rng = random.Random(7)
    for _ in range(50):
        t = next_attempt_at(pol, 1, now=0.0, rand=rng)
        assert 50.0 <= t <= 150.0
