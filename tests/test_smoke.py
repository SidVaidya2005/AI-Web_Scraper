"""Smoke test: the app package imports cleanly so CI has a green baseline."""


def test_app_package_imports() -> None:
    import app

    assert app is not None
