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