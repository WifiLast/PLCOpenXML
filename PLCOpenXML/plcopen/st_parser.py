import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import DataTypeUpdate, EnumValue, PouSection, PouUpdate, PouVariable, StVariable

KEYWORD_TO_POUTYPE = {
    "FUNCTION_BLOCK": "functionBlock",
    "FUNCTION": "function",
    "PROGRAM": "program",
}

SECTION_NAMES = {
    "VAR", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT",
    "VAR_TEMP", "VAR_EXTERNAL", "VAR_GLOBAL"
}

def extract_statements(text: str) -> List[Tuple[str, Optional[str]]]:
    """
    Safely tokenizes ST text and splits it into statements (by ;).
    It extracts block comments (* *) and associates the last comment with the preceding statement.
    Returns: [(statement_code, documentation_comment)]
    """
    pattern = re.compile(
        r"(?P<BLOCK_COMMENT>\(\*.*?\*\))|"
        r"(?P<LINE_COMMENT>//[^\n]*)|"
        r"(?P<STRING>'(?:[^']|'')*')|"
        r"(?P<WSTRING>\"(?:[^\"]|\"\")*\")|"
        r"(?P<PRAGMA>\{[^\}]*\})|" # like {attribute '...'}
        r"(?P<SEMI>;)|"
        r"(?P<CODE>[^('\"/\{;]+)|"
        r"(?P<OTHER>.)",
        re.DOTALL
    )

    statements = []
    current_stmt_parts = []
    last_comment = None

    for match in pattern.finditer(text):
        token_type = match.lastgroup
        value = match.group(0)

        if token_type in {"BLOCK_COMMENT", "LINE_COMMENT"}:
            if token_type == "BLOCK_COMMENT":
                comment_text = value[2:-2].strip()
            else:
                comment_text = value[2:].strip()
            if comment_text:
                last_comment = comment_text

        elif token_type in {"STRING", "WSTRING", "CODE", "OTHER", "PRAGMA"}:
            if token_type != "PRAGMA":  # Ignore pragmas in declarations
                current_stmt_parts.append(value)

        elif token_type == "SEMI":
            stmt = "".join(current_stmt_parts).strip()
            if stmt:
                statements.append((stmt, last_comment))
            current_stmt_parts = []
            last_comment = None

    # Handle remaining if not terminated by ;
    stmt = "".join(current_stmt_parts).strip()
    if stmt:
        statements.append((stmt, last_comment))

    return statements

def parse_pou_variable_stmt(code: str, documentation: Optional[str]) -> PouVariable:
    """Parses a single ST variable declaration statement."""
    # Example raw statement: "myVar AT %IX0.0 : BOOL := TRUE"
    
    parts = code.split(":", 1)
    if len(parts) == 1:
        raise ValueError(f"Invalid variable declaration without type: {code}")
    
    left = parts[0].strip()   # "myVar AT %IX0.0" or "myVar"
    right = parts[1].strip()  # "BOOL := TRUE"
    
    # Handle AT address
    at_parts = left.split(" AT ", 1)
    if len(at_parts) > 1:
        name = at_parts[0].strip()
    else:
        # Some users might use lowercase ' at ' or just space
        m = re.match(r"(?i)^(\w+)\s+at\s+(.+)$", left)
        if m:
            name = m.group(1).strip()
        else:
            name = left.strip()
    
    type_and_init = right
    initial_value = None
    
    if " := " in type_and_init:
        t_parts = type_and_init.split(" := ", 1)
        type_text = t_parts[0].strip()
        initial_value = t_parts[1].strip()
    # Also attempt standard assignment :=
    elif ":=" in type_and_init:
        t_parts = type_and_init.split(":=", 1)
        type_text = t_parts[0].strip()
        initial_value = t_parts[1].strip()
    else:
        type_text = type_and_init.strip()

    return PouVariable(
        name=name,
        type_text=type_text,
        initial_value=initial_value,
        documentation=documentation
    )

def read_st_file(path: Path) -> str:
    """Tries UTF-8, then falls back to CP1252 (common on Windows)."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="cp1252")
        except UnicodeDecodeError:
            return path.read_text(encoding="iso-8859-1")

def parse_pou_st_file(path: Path) -> Optional[PouUpdate]:
    try:
        text = read_st_file(path)
    except Exception as e:
        print(f"Error: could not read {path}: {e}")
        return None
    
    # Simple regex to extract header and body, robust against newlines
    header_block = ""
    body = ""
    
    # Find the START of the header: ignores pragmas and leading standalone comments.
    # Handles both single-line (* ... *) and multi-line block comments.
    lines = text.splitlines()
    header_index = 0
    in_block_comment = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if in_block_comment:
            if "*)" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("{attribute "):
            continue
        if stripped.startswith("(*"):
            if stripped.endswith("*)") and stripped.count("(*") == 1:
                # Single-line block comment, skip it
                continue
            else:
                # Multi-line block comment opening, skip until closing
                in_block_comment = True
                continue
        if stripped.startswith("//"):
            continue
        if stripped:
            header_index = i
            break
            
    if header_index >= len(lines):
        return None

    # Identify if it's purely a VAR_GLOBAL file or a POU (Function/Program/FB)
    first_meaningful_line = lines[header_index].strip()
    
    is_global_vars = False
    pou_name = path.stem
    pou_type = "globalVars"
    return_type = None
    
    if re.match(r"(?i)^VAR_GLOBAL\b", first_meaningful_line):
        is_global_vars = True
        body_start = len(lines)
    else:
        # Match POU header, e.g. "FUNCTION_BLOCK my_block"
        header_re = re.match(
            r"(?i)^(FUNCTION_BLOCK|FUNCTION|PROGRAM)\s+([A-Za-z0-9_]+)"
            r"(?:\s+EXTENDS\s+([A-Za-z0-9_.]+))?"
            r"(?:\s+IMPLEMENTS\s+([^:]+?))?"
            r"(?:\s*:\s*(.+))?"
            r"\s*$",
            first_meaningful_line
        )
        if not header_re:
            return None
        keyword = header_re.group(1).upper()
        pou_name = header_re.group(2)
        extends_name = header_re.group(3)
        implements_names = [part.strip() for part in (header_re.group(4) or "").split(",") if part.strip()]
        return_type = header_re.group(5)
        if keyword in KEYWORD_TO_POUTYPE:
            pou_type = KEYWORD_TO_POUTYPE[keyword]
        if pou_type != "function":
            return_type = None
            
        is_global_vars = False

    sections: List[PouSection] = []
    
    # Find VAR ... END_VAR blocks
    var_block_re = re.compile(
        r"(?im)^\s*(VAR_GLOBAL|VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_TEMP|VAR_EXTERNAL|VAR)"
        r"(?P<qualifiers>(?:\s+(?:CONSTANT|RETAIN|PERSISTENT))*)\s*$"
        r"(?P<content>.*?)"
        r"(?=^\s*END_VAR\b)",
        re.DOTALL,
    )
    
    # To correctly extract the declaration part versus the execution part in POUs:
    # Everything after the final END_VAR is the body (unless it's globalVars which has no body)
    last_end_var = -1
    for m in re.finditer(r"(?i)\bEND_VAR\b", text):
        last_end_var = m.end()

    if is_global_vars:
        declaration_text = text
        body = ""
    else:
        if last_end_var != -1:
            declaration_text = text[:last_end_var]
            body_text = text[last_end_var:]
            # Remove leading whitespace but preserve code indentation
            body = body_text.lstrip("\r\n \t")
            # Strip trailing END_FUNCTION_BLOCK / END_PROGRAM / END_FUNCTION
            body = re.sub(
                r"\s*\b(END_FUNCTION_BLOCK|END_PROGRAM|END_FUNCTION)\b\s*$",
                "",
                body,
                flags=re.IGNORECASE,
            ).rstrip("\r\n")
        else:
            declaration_text = text
            body = ""

    for match in var_block_re.finditer(declaration_text):
        section_type = match.group(1).upper()
        qualifiers = {part.upper() for part in match.group("qualifiers").split()}
        content = match.group("content")
        
        statements = extract_statements(content)
        parsed_vars = []
        for stmt_code, doc in statements:
            if stmt_code:
                try:
                    parsed_vars.append(parse_pou_variable_stmt(stmt_code, doc))
                except Exception as e:
                    print(f"Warning: failed to parse variable '{stmt_code}' in {path}: {e}")
                    
        sections.append(
            PouSection(
                kind=section_type,
                variables=parsed_vars,
                retain="RETAIN" in qualifiers,
                persistent="PERSISTENT" in qualifiers,
                constant="CONSTANT" in qualifiers,
            )
        )

    return PouUpdate(
        name=pou_name,
        pou_type=pou_type,
        return_type=return_type.strip() if return_type else None,
        sections=sections,
        body=body,
        extends=extends_name.strip() if not is_global_vars and extends_name else None,
        implements=implements_names if not is_global_vars and implements_names else None,
    )


def parse_data_type_st_file(path: Path) -> Optional[DataTypeUpdate]:
    try:
        text = read_st_file(path)
    except Exception as e:
        print(f"Error: could not read {path}: {e}")
        return None
    lines = text.splitlines()

    header_index = None
    in_block_comment = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if in_block_comment:
            if "*)" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("{attribute "):
            continue
        if stripped.startswith("(*"):
            if stripped.endswith("*)") and stripped.count("(*") == 1:
                continue
            else:
                in_block_comment = True
                continue
        if stripped.startswith("//"):
            continue
        header_index = i
        break

    if header_index is None:
        return None

    header_match = re.match(r"(?i)^TYPE\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*$", lines[header_index].strip())
    if not header_match:
        return None

    # Ignore any generated metadata comments before the TYPE header so comment
    # text containing words like "STRUCT" cannot be parsed as a field.
    parse_text = "\n".join(lines[header_index:])
    struct_match = re.search(r"(?is)\bSTRUCT\b(?P<content>.*?)\bEND_STRUCT\b", parse_text)
    if struct_match:
        fields: List[PouVariable] = []
        for stmt_code, doc in extract_statements(struct_match.group("content")):
            if not stmt_code:
                continue
            try:
                fields.append(parse_pou_variable_stmt(stmt_code, doc))
            except Exception as exc:
                print(f"Warning: failed to parse data type field '{stmt_code}' in {path}: {exc}")

        return DataTypeUpdate(name=header_match.group(1), fields=fields, kind="struct")

    enum_match = re.search(r"(?is)^TYPE\s+[A-Za-z_][A-Za-z0-9_]*\s*:\s*\((?P<content>.*?)\)\s*;\s*END_TYPE\b", parse_text.strip())
    if enum_match:
        enum_values: List[EnumValue] = []
        for raw_item in enum_match.group("content").split(","):
            item = raw_item.strip()
            if not item:
                continue
            if ":=" in item:
                name, value = item.split(":=", 1)
                enum_values.append(EnumValue(name=name.strip(), value=value.strip()))
            else:
                enum_values.append(EnumValue(name=item))
        return DataTypeUpdate(name=header_match.group(1), enum_values=enum_values, kind="enum")

    return None

def parse_st_file(path: Path) -> Tuple[str, List[StVariable]]:
    """Parse flat KBUS `.st` files for insert_changes assignment."""
    variables: List[StVariable] = []
    text = path.read_text(encoding="utf-8")
    var_block_re = re.compile(
        r"(?<=\b)(VAR_GLOBAL|VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_TEMP|VAR_EXTERNAL|VAR)(?=\b)"
        r"(.*?)"
        r"(?=\bEND_VAR\b)",
        re.DOTALL | re.IGNORECASE
    )

    declaration_regions = [match.group(2) for match in var_block_re.finditer(text)]
    if not declaration_regions:
        declaration_regions = [text]

    for declaration_text in declaration_regions:
        statements = extract_statements(declaration_text)
        for stmt_code, doc in statements:
            if not stmt_code:
                continue
            try:
                v = parse_pou_variable_stmt(stmt_code, doc)
                address = ""
                # Reconstruct address if AT exists purely through regex or split.
                m = re.search(r"(?i)\bAT\s+(%[IQM][BWXDL*][\d\.]+)", stmt_code)
                if m:
                    address = m.group(1).upper()

                variables.append(StVariable(
                    name=v.name,
                    address=address,
                    type_name=v.type_text,
                    comment=doc if doc else ""
                ))
            except Exception:
                pass  # Skip invalid

    return path.stem, variables
