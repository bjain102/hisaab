"""Serving-topology tests for tasks 0.6/2.5: SPA at /, API never shadowed,
graceful fallback when the frontend isn't built. Legacy Jinja UI and its
tests were retired in task 2.5 — the new UI is the only UI now."""
import app as app_module


def test_spa_serves_built_index(client, tmp_path, monkeypatch):
    dist = tmp_path / 'dist'
    dist.mkdir()
    (dist / 'index.html').write_text('<div id="root">SPA-MARKER</div>')
    (dist / 'app.js').write_text('// asset')
    monkeypatch.setattr(app_module, 'FRONTEND_DIST', str(dist))

    assert b'SPA-MARKER' in client.get('/').data
    # client-side routes survive refresh via index fallback
    assert b'SPA-MARKER' in client.get('/kit').data
    assert b'SPA-MARKER' in client.get('/transactions').data
    # real files are served as themselves
    assert b'// asset' in client.get('/app.js').data


def test_spa_fallback_message_when_not_built(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, 'FRONTEND_DIST', str(tmp_path / 'nowhere'))
    resp = client.get('/')
    assert resp.status_code == 503
    assert b'build.ps1' in resp.data


def test_api_paths_never_fall_through_to_spa(client, tmp_path, monkeypatch):
    dist = tmp_path / 'dist'
    dist.mkdir()
    (dist / 'index.html').write_text('SPA-MARKER')
    monkeypatch.setattr(app_module, 'FRONTEND_DIST', str(dist))

    resp = client.get('/api/definitely-not-a-real-endpoint')
    assert resp.status_code == 404
    assert b'SPA-MARKER' not in resp.data

    # registered API routes still work with the catch-all present
    assert client.get('/api/cards').status_code == 200


def test_legacy_and_clear_are_gone(client, tmp_path, monkeypatch):
    # A built frontend is staged explicitly, the same way the tests above do
    # it: this asserts a ROUTING fact (/legacy has no handler of its own), not
    # "someone ran build.ps1 before pytest". Without this the test passes only
    # on a machine that happens to have frontend/dist lying around, and 503s
    # on a fresh clone.
    dist = tmp_path / 'dist'
    dist.mkdir()
    (dist / 'index.html').write_text('<div id="root"></div>')
    monkeypatch.setattr(app_module, 'FRONTEND_DIST', str(dist))

    # /legacy is no longer a distinct route — it falls through to the SPA
    # catch-all exactly like any other unknown client path (/kit,
    # /transactions, ...), so it's a 200 serving the new UI's shell, not a
    # 404. What must actually be gone is the old Jinja page underneath it.
    resp = client.get('/legacy')
    assert resp.status_code == 200
    assert b'nav-item' not in resp.data  # the legacy template's own marker

    # The catch-all route only accepts GET, so a POST to a now-unregistered
    # path is a 405 (method not allowed) rather than reaching the GET-only
    # abort(404) guard — either way, no clear_data() handler exists anymore.
    assert client.post('/api/clear').status_code == 405
