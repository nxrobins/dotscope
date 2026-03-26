"""Hand-written help text following the voice spec.

Dense, no filler, examples before options. argparse handles parsing;
this module handles display.
"""

HELP_ROOT = """\
Usage: dotscope <command>

  ingest .                  Learn a codebase
  resolve <scope>           Serve context to an agent
  check                     Validate staged changes
  intent                    Declare architectural direction
  conventions               View and manage conventions
  voice                     View and manage code style
  diff --staged             Semantic diff
  bench                     Performance metrics
  test-compiler             Regression suite
  debug --last              Diagnose a bad session
  health                    Scope staleness and drift
  hook install              Post-commit feedback loop

Run dotscope <command> --help for details."""

HELP_INGEST = """\
Usage: dotscope ingest <path> [options]

  dotscope ingest .                    Full codebase ingest
  dotscope ingest auth/                Single module
  dotscope ingest . --max-commits 500  Deeper history mining
  dotscope ingest . --quiet            Suppress progress (for CI)

Options:
  --max-commits <n>    Git commits to mine (default: 500)
  --no-history         Skip git history mining
  --no-docs            Skip doc absorption
  --quiet              Suppress progress output
  --dry-run            Show what would be generated without writing"""

HELP_RESOLVE = """\
Usage: dotscope resolve <scope> [options]

  dotscope resolve auth                Files and context for auth/
  dotscope resolve auth --budget 4000  Best 4K tokens
  dotscope resolve auth+payments       Union of two scopes
  dotscope resolve auth@context        Context only, no files

Options:
  --budget <tokens>    Token limit
  --task <description> Filter constraints by relevance
  --json               Machine-readable output
  --no-related         Don't follow related scopes"""

HELP_CHECK = """\
Usage: dotscope check [options]

  dotscope check                          Validate staged changes
  dotscope check --diff changes.patch     Check arbitrary diff
  dotscope check --backtest --commits 10  Replay history
  dotscope check --acknowledge <id>       Acknowledge a hold

Options:
  --staged             Check staged changes (default)
  --diff <file>        Check arbitrary diff file
  --backtest           Replay commits instead of checking staged
  --commits <n>        Commits to replay (with --backtest)
  --acknowledge <id>   Acknowledge a hold and proceed
  --json               Machine-readable output"""

HELP_INTENT = """\
Usage: dotscope intent <action> [options]

  dotscope intent list                                    Show all intents
  dotscope intent add decouple auth/ payments/            Decouple modules
  dotscope intent add freeze core/                        Freeze a module
  dotscope intent add deprecate old.py --replacement new.py
  dotscope intent remove <id>                             Remove an intent

Directives:
  decouple <mod> <mod>   Discourage new coupling between modules
  deprecate <file>       Flag new usage as a hold
  freeze <module>        Require acknowledgment for any change
  consolidate <m> <m>    Encourage merging toward a target"""

HELP_CONVENTIONS = """\
Usage: dotscope conventions [options]

  dotscope conventions                List all conventions + compliance
  dotscope conventions --discover     Re-run discovery against codebase
  dotscope conventions --accept       Accept all discovered conventions
  dotscope conventions --review       Interactive review

Options:
  --discover           Re-run convention discovery
  --accept             Accept discovered conventions
  --review             Review discovered conventions interactively"""

HELP_VOICE = """\
Usage: dotscope voice [options]

  dotscope voice                      Show current voice config
  dotscope voice --upgrade typing     Upgrade enforcement level
  dotscope voice --json               Machine-readable output

Options:
  --upgrade <rule>     Upgrade enforcement (typing, bare_excepts)
  --json               Machine-readable output"""

HELP_DIFF = """\
Usage: dotscope diff [options]

  dotscope diff --staged               Semantic diff of staged changes
  dotscope diff HEAD~1                  Semantic diff against last commit
  dotscope diff HEAD~5..HEAD            Range of commits

Options:
  --staged             Diff staged changes (default)
  --json               Machine-readable output"""

HELP_BENCH = """\
Usage: dotscope bench [options]

  dotscope bench                       Full benchmark report
  dotscope bench --json                Machine-readable output

Options:
  --json               Machine-readable output"""

HELP_TEST_COMPILER = """\
Usage: dotscope test-compiler [options]

  dotscope test-compiler               Replay all regression cases
  dotscope test-compiler --scope auth  Replay regressions for auth only

Options:
  --scope <name>       Filter to a specific scope"""

HELP_DEBUG = """\
Usage: dotscope debug [options]

  dotscope debug --last                Debug most recent bad session
  dotscope debug <session_id>          Debug a specific session
  dotscope debug --list                List sessions with low recall

Options:
  --last               Debug most recent session with low recall
  --list               List debuggable sessions
  --json               Machine-readable output"""

HELP_HEALTH = """\
Usage: dotscope health [options]

  dotscope health                      All scopes
  dotscope health auth                 Single scope
  dotscope health --json               Machine-readable output

Options:
  --json               Machine-readable output"""

HELP_HOOK = """\
Usage: dotscope hook <action>

  dotscope hook install                Install pre-commit + post-commit hooks
  dotscope hook claude                 Install Claude Code pre-commit enforcement
  dotscope hook uninstall              Remove all dotscope hooks
  dotscope hook status                 Check what's installed

Pre-commit blocks commits with HOLDs. Post-commit records observations.
Claude Code hook is defense-in-depth for Claude Code users."""

HELP_COMMANDS = {
    "ingest": HELP_INGEST,
    "resolve": HELP_RESOLVE,
    "check": HELP_CHECK,
    "intent": HELP_INTENT,
    "conventions": HELP_CONVENTIONS,
    "diff": HELP_DIFF,
    "voice": HELP_VOICE,
    "bench": HELP_BENCH,
    "test-compiler": HELP_TEST_COMPILER,
    "debug": HELP_DEBUG,
    "health": HELP_HEALTH,
    "hook": HELP_HOOK,
}


def print_help(command=None):
    """Print help for a command, or root help if no command given."""
    if command is None:
        print(HELP_ROOT)
    elif command in HELP_COMMANDS:
        print(HELP_COMMANDS[command])
    else:
        import sys
        print(f"Unknown command: {command}\n")
        print("Run dotscope --help to see available commands.")
        sys.exit(1)
