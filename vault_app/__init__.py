from __future__ import annotations

import os

from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import inspect, text
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


def ensure_schema_compatibility() -> None:
    inspector = inspect(db.engine)
    if not inspector.has_table("transfer_entries"):
        return

    columns = {column["name"] for column in inspector.get_columns("transfer_entries")}
    statements: list[str] = []

    if "asset_symbol" not in columns:
        statements.append(
            "ALTER TABLE transfer_entries ADD COLUMN asset_symbol VARCHAR(20) NOT NULL DEFAULT 'BNB'"
        )
    if "token_contract" not in columns:
        statements.append(
            "ALTER TABLE transfer_entries ADD COLUMN token_contract VARCHAR(120) NULL"
        )
    if "token_decimals" not in columns:
        statements.append(
            "ALTER TABLE transfer_entries ADD COLUMN token_decimals INT NULL"
        )

    if statements:
        with db.engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))


def create_app() -> Flask:
    load_dotenv()

    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "replace-me-in-env")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL",
        "sqlite:///bnb_wallet_vault.db",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["ENCRYPTION_PEPPER"] = os.getenv("ENCRYPTION_PEPPER", "")
    app.config["BSC_RPC_URL"] = os.getenv("BSC_RPC_URL", "").strip()
    app.config["BSC_CHAIN_ID"] = int(os.getenv("BSC_CHAIN_ID", "56"))
    app.config["BSC_SEND_GAS_BUFFER_PERCENT"] = int(
        os.getenv("BSC_SEND_GAS_BUFFER_PERCENT", "110")
    )
    app.config["BSC_USDT_CONTRACT"] = os.getenv(
        "BSC_USDT_CONTRACT",
        "0x55d398326f99059fF775485246999027B3197955",
    ).strip()
    app.config["BSC_USDT_DECIMALS"] = int(os.getenv("BSC_USDT_DECIMALS", "18"))

    if not app.config["ENCRYPTION_PEPPER"]:
        raise RuntimeError("ENCRYPTION_PEPPER is required before the app can start.")

    db.init_app(app)

    from . import models
    from .routes import main_bp

    app.register_blueprint(main_bp)

    with app.app_context():
        db.create_all()
        ensure_schema_compatibility()

    @app.cli.command("init-db")
    def init_db() -> None:
        db.create_all()
        print("Database tables are ready.")

    return app
