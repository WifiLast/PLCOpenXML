# PLCOpener Tools

A Python package for extracting and inserting Structured Text (ST) code in PLCOpen XML files (CODESYS).

## Installation

You can install the package locally using pip:

```bash
pip install .
```

## Usage

After installation, two command-line tools are available:

### Extracting ST code

```bash
plcopen-extract project.xml -o output_dir
```

### Inserting changes back

```bash
plcopen-insert project.xml --st-dir output_dir -o updated_project.xml
```

## Programmatic Usage

You can also use the package in your own Python scripts:

```python
from plcopener import ProjectExtractor, ProjectInserter

# Extract
extractor = ProjectExtractor("project.xml")
extractor.extract("st_output")

# Insert
inserter = ProjectInserter("project.xml")
inserter.insert("st_output", output_path="updated.xml")
```
