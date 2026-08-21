from vault_app import create_app


app = create_app()


if __name__ == "__main__":
    # Werkzeug's process reloader can fail to inherit its listening socket on
    # Windows (WinError 10038). Keep debug mode, but restart manually on edits.
    app.run(debug=True, use_reloader=False)
