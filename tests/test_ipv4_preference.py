"""Tests for the IPv4 preference resolver wrapper."""

import socket

import pytest

from mobilerun.agent.utils.ipv4_preference import prefer_ipv4_when_supported

_IPV4_ENTRY = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
_IPV6_ENTRY = (
    socket.AF_INET6,
    socket.SOCK_STREAM,
    6,
    "",
 ("2606:2800:220:1:248:1893:25c8:1946", 443, 0, 0),
)


@pytest.fixture()
def restore_getaddrinfo(monkeypatch):
    original = socket.getaddrinfo
    yield
    socket.getaddrinfo = original


def test_drops_aaaa_when_a_records_exist(restore_getaddrinfo, monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [_IPV6_ENTRY, _IPV4_ENTRY],
    )

    prefer_ipv4_when_supported()

    results = socket.getaddrinfo("example.com", 443)
    assert results == [_IPV4_ENTRY]


def test_keeps_aaaa_only_hosts(restore_getaddrinfo, monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [_IPV6_ENTRY],
    )

    prefer_ipv4_when_supported()

    results = socket.getaddrinfo("example.com", 443)
    assert results == [_IPV6_ENTRY]


def test_is_idempotent(restore_getaddrinfo):
    prefer_ipv4_when_supported()
    first = socket.getaddrinfo
    prefer_ipv4_when_supported()

    assert socket.getaddrinfo is first


def test_env_kill_switch(restore_getaddrinfo, monkeypatch):
    monkeypatch.setenv("MOBILERUN_DISABLE_IPV4_PREFERENCE", "1")
    unpatched = socket.getaddrinfo

    prefer_ipv4_when_supported()

    assert socket.getaddrinfo is unpatched
