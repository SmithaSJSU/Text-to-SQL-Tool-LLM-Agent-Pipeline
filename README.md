# Text-to-SQL Tool — LLM Agent Pipeline

A schema-aware natural language → SQL translation system, built with LangChain
and LLM APIs (Anthropic Claude / OpenAI, pluggable), with an automated
validation and sanitization layer that sits between the model and the
database to prevent malformed queries and SQL injection.

```
Question
   │
   ▼
SchemaIntrospector  ──►  introspects live DB (tables, columns, types, PK/FK)
   │
   ▼
PromptBuilder  ──►  injects schema + FK relationships + constraints into prompt
   │
   ▼
LLMClient  ──►  LangChain call to Claude / GPT, deterministic (temperature=0)
   │
   ▼
SQLValidator  ──►  AST-parses output, allow-lists SELECT-only, checks every
   │                table/column against the real schema, blocks injection
   │                patterns, enforces a row LIMIT
   ▼
QueryExecutor  ──►  runs the validated, read-only query (optional)
```

## Why this design

- **Schema-aware, not schema-blind.** The model never has to guess table or
  column names — the exact live schema (including declared foreign keys) is
  introspected and injected into the prompt every time, so joins use real
  relationships instead of invented ones.
- **Never trust generated SQL as a string.** The validator parses every
  candidate query into a real AST (`sqlglot`) rather than pattern-matching on
  text. Unparseable input is rejected outright, before it ever touches a
  database connection.
- **Allow-list, not block-list.** Only `SELECT` (optionally with `WITH` CTEs)
  is permitted. Everything else — `INSERT`, `UPDATE`, `DELETE`, `DROP`,
  `ALTER`, `PRAGMA`, `ATTACH`, stacked statements, comments — is rejected by
  default, rather than trying to enumerate every dangerous pattern.
- **Schema conformance checks catch hallucination and injection alike.**
  Every referenced table/column is checked against the introspected schema.
  This blocks both a model inventing a `notes` column that doesn't exist and
  an attacker trying to reach a table that was never exposed to the model.
- **Defense in depth.** Comment stripping, semicolon/stacked-statement
  detection, and dangerous-function detection (`xp_cmdshell`, `LOAD_FILE`,
  `INTO OUTFILE`) run as a cheap first pass before the AST-level checks.

## Project layout

```
text2sql/
  schema_introspector.py   SQLAlchemy-based schema introspection
  prompt_builder.py        Dynamic prompt construction w/ schema injection
  llm_client.py             LangChain wrapper (Anthropic / OpenAI)
  sql_validator.py          AST-based validation & sanitization
  query_executor.py         Executes validated, read-only SQL
  pipeline.py               Orchestrates the full flow
  cli.py                    Interactive CLI
sample_db/
  create_sample_db.py       Generates a demo e-commerce SQLite DB
tests/
  test_schema_introspector.py
  test_prompt_builder.py
  test_sql_validator.py     Includes adversarial/injection test cases
  test_pipeline.py          End-to-end tests with a fake LLM client
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY or OPENAI_API_KEY
python sample_db/create_sample_db.py
```

## Usage

### CLI

```bash
python -m text2sql.cli --db sqlite:///sample_db/ecommerce.db
> How many orders were placed by each country?
```

Or non-interactively:

```bash
python -m text2sql.cli --db sqlite:///sample_db/ecommerce.db \
  --question "What are the top 3 most expensive products?"
```

Use `--no-execute` to only generate + validate the SQL without running it.
Use `--provider openai --model gpt-4o` to switch providers.

### As a library

```python
from text2sql import TextToSQLPipeline, LLMConfig

pipeline = TextToSQLPipeline(
    connection_string="sqlite:///sample_db/ecommerce.db",
    llm_config=LLMConfig(provider="anthropic", model="claude-sonnet-4-6"),
)

result = pipeline.ask("Which customers have never placed an order?")

if result.is_valid:
    print(result.sql)
    print(result.rows)
else:
    print("Rejected:", result.errors)
```

## Running tests

No API key required — the pipeline tests use a fake LLM client so the full
flow (including injection attempts) is exercised deterministically:

```bash
pytest tests/ -v
```

## Extending to other databases

Swap the `connection_string` for any SQLAlchemy-supported DB
(`postgresql://...`, `mysql+pymysql://...`, etc.) and set `dialect`
accordingly (e.g. `"postgres"`) — the introspector, prompt builder, and
validator all work off the same abstraction.

## Known limitations

- Column-level checks for unqualified columns in multi-table joins are
  best-effort (ambiguous references produce a warning, not a hard failure),
  since resolving them precisely requires full join-graph analysis.
- The validator does not currently parse `HAVING`/window-function edge cases
  exhaustively — it's tuned for the common analytical-query surface, not a
  full SQL semantic verifier.
- Row-level / column-level access control (e.g. "this user can't see
  `salary`") is out of scope here; add a masking layer or DB-level views if
  needed.
