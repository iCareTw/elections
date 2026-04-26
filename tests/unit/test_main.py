import main


def test_main_dispatches_serve_ui(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(main, "_run_identity_ui", lambda: calls.append("serve-ui"))

    main.main(["serve-ui"])

    assert calls == ["serve-ui"]
