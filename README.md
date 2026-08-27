# 秩宗 (zhizong)

A contract validation tool that validates a corpus of contract documents against the grammar shipped inside the package.

## Installation

```bash
pip install zhizong
```

## Usage

```bash
zhizong validate [--config PATH]
zhizong --version
```

## Configuration

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `namespace` | Yes | - | The namespace identifier for the contract documents |
| `contracts_root` | No | `contracts` | The root directory containing contract documents |

## Grammar Specification

The normative format specification is defined in `src/zhizong/versions/1.yaml`.

## Field-Table Type Vocabulary

Field-table `Type` expressions compile to JSON Schema (draft 2020-12):

| Expression | Compiles to | One-line example |
|------------|-------------|------------------|
| `string` / `integer` / `number` / `boolean` | the bare JSON type | `{"type": "string"}` |
| `object` (with `Fields`) | nested object schema | `{"type": "object", ...}` |
| `array<T>` | array of `T`, nestable | `array<string>` → `{"type": "array", "items": {"type": "string"}}` |
| scalar / record structure name | the referenced structure's schema (records via `$defs`/`$ref`) | `FeedId` |
| `T?` | nullable: `T` or `null` | `MediaFile?` → `{"anyOf": [{"type": "string", "pattern": ...}, {"type": "null"}]}` |
| `a|b|c` | string-literal enum | `pending|ok` → `{"enum": ["pending", "ok"]}` |

Notes:

* `?` composes with any inner form and is stripped before reference lookup: `integer?`, `MediaFile?`, `array<object>?` (nullable array — distinct from `array<object?>`, nullable items).
* `|` alternatives must be bare literals (`^[A-Za-z0-9_.-]+$`) and split outside any `<>`; parentheses grouping a whole expression are pure syntax: `(pending|ok)?` is a nullable enum.
* `Required: true` is orthogonal to `?`: a nullable-but-required field's key must exist, its value may be `null`.