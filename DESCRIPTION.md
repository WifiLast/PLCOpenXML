# PLCOpener: Structured Text Engineering Tools

**PLCOpener** is a powerful Python suite designed to bridge the gap between traditional PLC development and modern software engineering workflows. It enables developers to treat PLC code like standard source code, facilitating version control, automated refactoring, and CI/CD integration for CODESYS-based projects.

## Project Purpose

PLC projects are typically stored in monolithic XML files (PLCOpen XML) or binary formats, making them difficult to track in Git or edit with external text editors. **PLCOpener** solves this by:

1.  **Extracting** Structured Text (ST) into readable, individual files.
2.  **Reconstructing** the project's internal folder hierarchy for intuitive navigation.
3.  **Inserting** modified code back into the original XML project without breaking metadata or IDs.

## Key Features

*   **Project Reconstruction**: Automatically recreates the CODESYS folder structure on your filesystem.
*   **Multi-Resource Support**: Handles complex projects with multiple applications and hardware resources.
*   **Resilient Parsing**: Intelligent XML handling that can recover from truncated or malformed exports.
*   **Type Awareness**: Extracts and inserts Data Types (DUTs), Global Variable Lists (GVLs), and POU logic.
*   **Dual Interface**: Complete CLI for automation and a Python API for custom tooling.

---

## Example Walkthrough

This example demonstrates how to extract code from a project, modify it, and re-integrate the changes.

### 1. Extraction (CLI)

First, extract the project structure and ST code into a workspace:

```bash
plcopen-extract project_export.xml -o my_workspace
```

This creates a directory `my_workspace` where your POUs are organized exactly as they appear in the PLC tree:
```text
my_workspace/
├── Application/
│   ├── PLC_PRG.st
│   └── ControlLogic/
│       └── PID_Control.st
├── Global/
│   └── GVL_Constants.st
└── Types/
    └── ST_MotorData.st
```

### 2. Modification

Open `my_workspace/Application/PLC_PRG.st` in your favorite editor (e.g., VS Code) and add a variable or change the logic:

```pascal
PROGRAM PLC_PRG
VAR
    xStart : BOOL;
    iCounter : INT;
    sStatus : STRING := 'Running'; // Added or modified line
END_VAR

iCounter := iCounter + 1;
```

### 3. Insertion (CLI)

Sync your changes back into a new version of the XML project:

```bash
plcopen-insert project_export.xml --st-dir my_workspace -o project_updated.xml
```

### 4. Programmatic Integration (Python)

You can integrate these steps directly into your own Python scripts for automated transformations:

```python
from pathlib import Path
from plcopener import ProjectExtractor, ProjectInserter

# Initialize paths
source_xml = Path("project.xml")
workspace = Path("workspace")

# Extract
extractor = ProjectExtractor(source_xml)
extractor.extract(workspace)

# Perform custom logic (e.g., search and replace across all .st files)
# ...

# Insert back
inserter = ProjectInserter(source_xml)
inserter.insert(workspace, output_path="project_transformed.xml")
```

---

## Installation

```bash
pip install .
```

*Note: Requires Python 3.7+ and standard library modules.*
