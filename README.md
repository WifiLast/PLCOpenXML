# PLCOpener Tools

[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Proprietary-red.svg)](license.txt)

**PLCOpener** is a professional Python package for extracting and inserting Structured Text (ST) code in PLCOpen XML files (compatible with CODESYS, TwinCAT, etc.).

It allows developers to bridge the gap between monolithic XML exports and modern software engineering practices like Git version control, external code analysis, and automated refactoring.

## Features

- **Folder Reconstruction**: Rebuilds the project tree structure on your filesystem.
- **Resource Management**: Automatically detects and groups files by PLC applications/resources.
- **Resilient Parsing**: Robust handling of malformed or incomplete XML project files.
- **CLI & Library**: Full support for both command-line automation and programmatic use.

## Installation

```bash
pip install .
```

## Quick Start

### 1. Extracting ST code

```bash
plcopen-extract project.xml -o my_workspace
```

### 2. Modifying and Re-inserting

After editing the `.st` files in `my_workspace`, push the changes back:

```bash
plcopen-insert project.xml --st-dir my_workspace -o updated_project.xml
```

## Documentation

For a detailed project description and complete examples, please see [DESCRIPTION.md](DESCRIPTION.md).

## Usage Example (Library)

```python
from plcopener import ProjectExtractor, ProjectInserter

# Extract
ProjectExtractor("project.xml").extract("st_output")

# Insert
ProjectInserter("project.xml").insert("st_output", output_path="updated.xml")
```
