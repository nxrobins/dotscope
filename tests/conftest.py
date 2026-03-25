"""Shared test fixtures: temp projects with .scope files."""

import os
import pytest


@pytest.fixture
def tmp_project(tmp_path):
    """Create a simple project with .scope files for testing."""
    # Root .scopes index
    (tmp_path / ".scopes").write_text(
        "version: 1\n"
        "\n"
        "scopes:\n"
        "  auth:\n"
        "    path: auth/.scope\n"
        "    keywords: [authentication, login, JWT, session, token]\n"
        "  payments:\n"
        "    path: payments/.scope\n"
        "    keywords: [billing, stripe, invoice, subscription]\n"
        "\n"
        "defaults:\n"
        "  max_tokens: 8000\n"
        "  include_related: false\n"
    )

    # .git directory (for repo root detection)
    (tmp_path / ".git").mkdir()

    # Auth module
    auth = tmp_path / "auth"
    auth.mkdir()
    (auth / "__init__.py").write_text("# Auth module\n")
    (auth / "handler.py").write_text(
        "from models.user import User\n"
        "\n"
        "def login(username, password):\n"
        "    user = User.find(username)\n"
        "    return user.check_password(password)\n"
    )
    (auth / "tokens.py").write_text(
        "import time\n"
        "\n"
        "def create_jwt(user_id):\n"
        "    return {'user': user_id, 'exp': time.time() + 900}\n"
    )

    # Auth tests
    auth_tests = auth / "tests"
    auth_tests.mkdir()
    (auth_tests / "__init__.py").write_text("")
    fixtures = auth_tests / "fixtures"
    fixtures.mkdir()
    (fixtures / "users.json").write_text('[{"id": 1, "name": "test"}]')

    # Auth .scope
    (auth / ".scope").write_text(
        "description: Authentication and session management\n"
        "includes:\n"
        "  - auth/\n"
        "  - models/user.py\n"
        "excludes:\n"
        "  - auth/tests/fixtures/\n"
        "context: |\n"
        "  Auth uses JWT tokens with 15-min access / 7-day refresh.\n"
        "  Session store is Redis.\n"
        "  \n"
        "  ## Invariants\n"
        "  Never call .delete() on User, use .deactivate().\n"
        "  \n"
        "  ## Gotchas\n"
        "  OAuth provider config is fragile — check README first.\n"
        "related:\n"
        "  - payments/.scope\n"
        "tags:\n"
        "  - security\n"
        "  - session-management\n"
    )

    # Payments module
    payments = tmp_path / "payments"
    payments.mkdir()
    (payments / "__init__.py").write_text("# Payments\n")
    (payments / "billing.py").write_text(
        "def charge(user_id, amount):\n"
        "    pass\n"
    )

    # Payments .scope
    (payments / ".scope").write_text(
        "description: Payment processing and billing\n"
        "includes:\n"
        "  - payments/\n"
        "excludes:\n"
        "  - \"*.pyc\"\n"
        "context: |\n"
        "  Uses Stripe for payment processing.\n"
        "  All amounts in cents.\n"
        "tags:\n"
        "  - billing\n"
        "  - stripe\n"
    )

    # Models directory
    models = tmp_path / "models"
    models.mkdir()
    (models / "__init__.py").write_text("")
    (models / "user.py").write_text(
        "class User:\n"
        "    def __init__(self, id, name):\n"
        "        self.id = id\n"
        "        self.name = name\n"
        "\n"
        "    def deactivate(self):\n"
        "        self.active = False\n"
    )

    # Config directory (no .scope)
    config = tmp_path / "config"
    config.mkdir()
    (config / "settings.py").write_text("DEBUG = True\n")

    return tmp_path


@pytest.fixture
def scope_text():
    """Raw .scope file content for parser testing."""
    return (
        "description: Authentication and session management\n"
        "includes:\n"
        "  - auth/\n"
        "  - models/user.py\n"
        "  - config/auth_settings.py\n"
        "excludes:\n"
        "  - auth/tests/fixtures/\n"
        '  - "*.generated.py"\n'
        "context: |\n"
        "  Auth uses JWT tokens with 15-min access / 7-day refresh.\n"
        "  Session store is Redis (config/redis.py).\n"
        "  User model has soft deletes — never call .delete().\n"
        "related:\n"
        "  - payments/.scope  # shares user model\n"
        "  - api/.scope\n"
        "owners:\n"
        '  - "@alice"\n'
        '  - "@bob"\n'
        "tags:\n"
        "  - security\n"
        "  - session-management\n"
        "tokens_estimate: 1247\n"
    )
