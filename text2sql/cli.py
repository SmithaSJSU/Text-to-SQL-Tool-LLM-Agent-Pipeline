"""
Simple interactive CLI for the text-to-SQL pipeline.

Usage:
    python -m text2sql.cli --db sqlite:///sample_db/ecommerce.db
    python -m text2sql.cli --db sqlite:///sample_db/ecommerce.db --provider openai --model gpt-4o

Requires ANTHROPIC_API_KEY or OPENAI_API_KEY to be set in the environment
(or a .env file, if python-dotenv is installed) depending on --provider.
"""

from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

from .llm_client import LLMConfig
from .pipeline import TextToSQLPipeline


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Natural language to SQL CLI")
    parser.add_argument(
        "--db", required=True, help="SQLAlchemy connection string, e.g. sqlite:///path/to.db"
    )
    parser.add_argument("--provider", default="anthropic", choices=["anthropic", "openai"])
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--dialect", default="sqlite")
    parser.add_argument("--no-execute", action="store_true", help="Only generate + validate, don't run the query")
    parser.add_argument("--question", help="Ask a single question and exit (non-interactive mode)")
    args = parser.parse_args()

    pipeline = TextToSQLPipeline(
        connection_string=args.db,
        llm_config=LLMConfig(provider=args.provider, model=args.model),
        dialect=args.dialect,
    )

    def handle(question: str):
        result = pipeline.ask(question, execute=not args.no_execute)
        if not result.is_valid:
            print("❌ Query rejected by validator:")
            for e in result.errors or []:
                print(f"   - {e}")
            if result.raw_llm_response:
                print(f"\n(raw model response)\n{result.raw_llm_response}")
            return

        print(f"✅ SQL:\n{result.sql}\n")
        for w in result.warnings or []:
            print(f"⚠️  {w}")
        if result.rows is not None:
            print(f"\n{result.row_count} row(s):")
            print(json.dumps(result.rows, indent=2, default=str))

    if args.question:
        handle(args.question)
        return

    print("Text-to-SQL CLI. Type a question in plain English, or 'exit' to quit.")
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            break
        handle(question)


if __name__ == "__main__":
    sys.exit(main())
