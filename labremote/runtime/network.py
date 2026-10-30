"""InstrumentServer compatibility helpers for older/newer ZeroMQ clients.

Some instrumentserver client releases interpret Client(timeout=...) as a
millisecond value. Set the actual pyzmq receive timeout explicitly instead.
"""
from __future__ import annotations

import zmq


def configure_client_timeout(client, seconds: float = 20.0) -> int:
    milliseconds = int(float(seconds) * 1000)
    if milliseconds < 1000 or milliseconds > 300000:
        raise ValueError('Receive timeout must be between 1 and 300 seconds')
    sock = getattr(client, 'socket', None)
    if sock is None:
        raise RuntimeError('InstrumentServer Client has no ZeroMQ socket')
    sock.setsockopt(zmq.RCVTIMEO, milliseconds)
    client.recv_timeout = milliseconds
    if hasattr(client, 'recv_timeout_ms'):
        client.recv_timeout_ms = milliseconds
    return sock.getsockopt(zmq.RCVTIMEO)
