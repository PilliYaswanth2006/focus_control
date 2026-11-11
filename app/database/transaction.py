import threading
from contextlib import contextmanager
from flask import g, has_app_context
from app.database.connection import get_db


_local_state = threading.local()


def _get_tx_depths():
    if has_app_context():
        if "_tx_depths" not in g:
            g._tx_depths = {}
        return g._tx_depths
    if not hasattr(_local_state, "tx_depths"):
        _local_state.tx_depths = {}
    return _local_state.tx_depths


@contextmanager
def transaction(conn=None):
    """Manage explicit SQLite transactions and nested savepoints across services."""
    if conn is None:
        conn = get_db()

    depths = _get_tx_depths()
    conn_key = id(conn)
    depth = depths.get(conn_key, 0)

    if depth == 0:
        conn.execute("BEGIN IMMEDIATE")
        depths[conn_key] = 1
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            depths[conn_key] = 0
    else:
        sp_name = "sp_%d" % depth
        depths[conn_key] = depth + 1
        conn.execute("SAVEPOINT " + sp_name)
        try:
            yield conn
            conn.execute("RELEASE SAVEPOINT " + sp_name)
        except Exception:
            try:
                conn.execute("ROLLBACK TO SAVEPOINT " + sp_name)
                conn.execute("RELEASE SAVEPOINT " + sp_name)
            except Exception:
                pass
            raise
        finally:
            depths[conn_key] = depth
