"""Decode object replies from different InstrumentServer serializer versions."""
import ast
import json


def decode_object(raw, *, context='InstrumentServer response'):
    """Accept JSON text, an already decoded dict, or legacy dict repr.

    Never stringify a decoded object, replace quotes, or execute a reply.
    Device-specific schemas and interlocks remain the caller's responsibility.
    """
    if isinstance(raw, str) and raw.startswith('LRJSON1:'):
        try:
            data = json.loads(bytes.fromhex(raw[8:]).decode('utf-8'))
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError(f'{context}: invalid framed JSON response') from exc
        if not isinstance(data, dict): raise RuntimeError(f'{context}: expected an object')
        return data
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            try:
                data = ast.literal_eval(raw)
            except (ValueError, SyntaxError, TypeError, RecursionError) as exc:
                raise RuntimeError(f'{context}: invalid JSON/object response') from exc
    else:
        raise RuntimeError(f'{context}: unsupported response type {type(raw).__name__}')
    if not isinstance(data, dict):
        raise RuntimeError(f'{context}: expected an object')
    return data


def encode_object(data):
    """Protect JSON requests from recursive legacy transport conversion."""
    if not isinstance(data, dict): raise TypeError('Expected an object')
    return 'LRJSON1:' + json.dumps(data, ensure_ascii=True, allow_nan=False).encode('utf-8').hex()
