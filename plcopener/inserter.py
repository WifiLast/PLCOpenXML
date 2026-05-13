from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .models import DataTypeUpdate, PouSection, PouUpdate, PouVariable, StVariable
from .st_parser import parse_data_type_st_file, parse_pou_st_file, parse_st_file
from .xml_utils import (
    ADDDATA_OBJECTID,
    NS,
    NS_XHTML,
    find_child,
    get_object_id,
    get_project_structure,
    iter_children,
    local_name,
    p,
    remove_children,
    sanitize,
    set_text_child,
    xhtml_tag,
)

NAME_INDEX_RE = re.compile(r"^A(?P<index>\d+)_")
BIT_INDEX_RE = re.compile(r"\.Bit(?P<bit>\d+)\.")
PARAM_ID_RE = re.compile(r"^\d+$")
FIELD_DECL_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<type>[^;:=]+(?:\[[^\]]+\])?(?:\s+OF\s+[^;:=]+)?)"
    r"(?:\s*:=\s*(?P<init>.*?))?;\s*(?:\(\*\s*(?P<comment>.*?)\s*\*\))?\s*$"
)
FIELD_MAPPING_RE = re.compile(r"(?:^|\|\s*)Mapping:\s*(?P<mapping>Application\.[^|]+?)\s*$")

SECTION_TO_XML = {
    "VAR_INPUT": "inputVars",
    "VAR_OUTPUT": "outputVars",
    "VAR_IN_OUT": "inOutVars",
    "VAR": "localVars",
    "VAR_TEMP": "tempVars",
    "VAR_EXTERNAL": "externalVars",
    "VAR_GLOBAL": "globalVars",
}


@dataclass
class FieldbusVariableUpdate:
    name: str
    type_name: str
    initial_value: str | None
    mapping: str | None


def load_kbus_variables(kbus_dir: Path) -> dict[str, list[StVariable]]:
    result: dict[str, list[StVariable]] = {}
    for path in sorted(kbus_dir.glob("*.st")):
        if path.stem in {"Device", "Kbus"}:
            continue
        stem, variables = parse_st_file(path)
        if variables:
            result[stem] = variables
    return result


def load_fieldbus_variables(fieldbus_dir: Path) -> dict[str, list[FieldbusVariableUpdate]]:
    result: dict[str, list[FieldbusVariableUpdate]] = {}
    if not fieldbus_dir.exists():
        return result

    for path in sorted(fieldbus_dir.glob("*.st")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        in_var_global = False
        variables: list[FieldbusVariableUpdate] = []
        seen_mappings: set[str] = set()

        for line in lines:
            stripped = line.strip()
            if not in_var_global:
                if re.match(r"^VAR_GLOBAL(?:\s+(?:CONSTANT|RETAIN|PERSISTENT))*\s*$", stripped, re.IGNORECASE):
                    in_var_global = True
                continue

            if re.match(r"^END_VAR\b", stripped, re.IGNORECASE):
                break
            if not stripped or stripped.startswith("(*"):
                continue

            match = FIELD_DECL_RE.match(line)
            if match is None:
                continue

            comment = (match.group("comment") or "").strip()
            mapping_match = FIELD_MAPPING_RE.search(comment)
            mapping = mapping_match.group("mapping").strip() if mapping_match else None
            if mapping:
                if mapping in seen_mappings:
                    mapping = None
                else:
                    seen_mappings.add(mapping)
            variables.append(
                FieldbusVariableUpdate(
                    name=match.group("name").strip(),
                    type_name=match.group("type").strip(),
                    initial_value=(match.group("init") or "").strip() or None,
                    mapping=mapping,
                )
            )

        if not variables:
            continue
        result[path.stem] = variables
    return result


def load_pou_updates(
    st_dir: Path, exclude_dirs: list[Path] | None = None
) -> tuple[dict[str, PouUpdate], dict[str, PouUpdate]]:
    by_name: dict[str, PouUpdate] = {}
    by_relpath: dict[str, PouUpdate] = {}
    st_dir_resolved = st_dir.resolve()
    exclude_resolved = [path.resolve() for path in (exclude_dirs or []) if path.exists()]

    for path in sorted(st_dir.rglob("*.st")):
        if not path.is_file():
            continue
        if exclude_resolved:
            path_resolved = path.resolve()
            skip_path = False
            for exclude_path in exclude_resolved:
                if exclude_path == st_dir_resolved:
                    continue
                try:
                    path_resolved.relative_to(exclude_path)
                    skip_path = True
                    break
                except ValueError:
                    continue
            if skip_path:
                continue
        try:
            update = parse_pou_st_file(path)
        except Exception as e:
            print(f"Warning: could not parse POU {path}: {e}")
            update = None
        if update is not None:
            by_name[update.name] = update
            by_relpath[path.relative_to(st_dir).as_posix()] = update
    return by_name, by_relpath


def load_data_type_updates(
    st_dir: Path, exclude_dirs: list[Path] | None = None
) -> tuple[dict[str, DataTypeUpdate], dict[str, DataTypeUpdate]]:
    by_name: dict[str, DataTypeUpdate] = {}
    by_relpath: dict[str, DataTypeUpdate] = {}
    st_dir_resolved = st_dir.resolve()
    exclude_resolved = [path.resolve() for path in (exclude_dirs or []) if path.exists()]

    for path in sorted(st_dir.rglob("*.st")):
        if not path.is_file():
            continue
        if exclude_resolved:
            path_resolved = path.resolve()
            skip_path = False
            for exclude_path in exclude_resolved:
                if exclude_path == st_dir_resolved:
                    continue
                try:
                    path_resolved.relative_to(exclude_path)
                    skip_path = True
                    break
                except ValueError:
                    continue
            if skip_path:
                continue
        try:
            update = parse_data_type_st_file(path)
        except Exception as e:
            print(f"Warning: could not parse DataType {path}: {e}")
            update = None
        if update is not None:
            by_name[update.name] = update
            by_relpath[path.relative_to(st_dir).as_posix()] = update
    return by_name, by_relpath


def sort_name(name: str) -> tuple[int, str]:
    match = NAME_INDEX_RE.match(name)
    if match:
        return int(match.group("index")), name
    return 9999, name


def family_from_name(name: str) -> str:
    if "750_455" in name:
        return "750-455"
    if "750_497" in name:
        return "750-497"
    if "750_450" in name:
        return "750-450"
    if "750_597" in name:
        return "750-597"
    if "750_559" in name:
        return "750-559"
    if "750_430" in name or "75x_8DI" in name:
        return "8DI"
    if "750_530" in name or "75x_8DO" in name:
        return "8DO"
    return "other"


def build_variable_assignment(
    configuration_names: list[str], kbus_variables: dict[str, list[StVariable]]
) -> dict[str, list[StVariable]]:
    assignment: dict[str, list[StVariable]] = {}
    remaining = dict(kbus_variables)

    for name in configuration_names:
        if name in remaining:
            assignment[name] = remaining.pop(name)

    config_by_family: dict[str, list[str]] = {}
    for name in configuration_names:
        if name in assignment:
            continue
        config_by_family.setdefault(family_from_name(name), []).append(name)

    files_by_family: dict[str, list[str]] = {}
    for name in remaining:
        files_by_family.setdefault(family_from_name(name), []).append(name)

    for family, config_names in config_by_family.items():
        configs = sorted(config_names, key=sort_name)
        files = sorted(files_by_family.get(family, []), key=sort_name)
        for config_name, file_name in zip(configs, files):
            assignment[config_name] = remaining[file_name]

    return assignment


def sort_addr(address: str) -> tuple[int, int]:
    if not address:
        return 9999, 9999
    if address.startswith(("%IX", "%QX")):
        major, minor = address[3:].split(".")
        return int(major), int(minor)
    if address.startswith(("%IW", "%QW")):
        return int(address[3:]), 0
    if address.startswith(("%IB", "%QB")):
        return int(address[3:]), 0
    return 9999, 0


def ensure_mapping(parameter: ET.Element) -> ET.Element:
    mapping = find_child(parameter, "Mapping")
    if mapping is None:
        mapping = ET.SubElement(parameter, "Mapping")
    return mapping


def split_type_and_init(type_text: str) -> tuple[str, str | None]:
    if " := " not in type_text:
        return type_text, None
    left, right = type_text.split(" := ", 1)
    return left.strip(), right.strip()


def fieldbus_type_key(type_name: str | None) -> str:
    value = (type_name or "").strip().upper()
    if ":" in value:
        _, value = value.split(":", 1)
    if value.startswith("STRING[") or value.startswith("STRING("):
        return "STRING"
    if value.startswith("WSTRING[") or value.startswith("WSTRING("):
        return "WSTRING"
    return value


def longest_common_subsequence(left: list[str], right: list[str]) -> list[tuple[int, int]]:
    dp = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    for i in range(len(left) - 1, -1, -1):
        for j in range(len(right) - 1, -1, -1):
            if left[i] == right[j]:
                dp[i][j] = dp[i + 1][j + 1] + 1
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])

    matches: list[tuple[int, int]] = []
    i = 0
    j = 0
    while i < len(left) and j < len(right):
        if left[i] == right[j]:
            matches.append((i, j))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return matches


def build_type_node(parent: ET.Element, type_text: str) -> None:
    type_text = type_text.strip()

    array_match = re.fullmatch(r"ARRAY\s*\[(.+)\]\s+OF\s+(.+)", type_text, re.IGNORECASE)
    if array_match:
        dims_text, base_type = array_match.groups()
        array_elem = ET.SubElement(parent, p("array"))
        for dim_text in [part.strip() for part in dims_text.split(",")]:
            lower, upper = [part.strip() for part in dim_text.split("..", 1)]
            ET.SubElement(array_elem, p("dimension"), {"lower": lower, "upper": upper})
        base_type_elem = ET.SubElement(array_elem, p("baseType"))
        build_type_node(base_type_elem, base_type)
        return

    ptr_match = re.fullmatch(r"POINTER\s+TO\s+(.+)", type_text, re.IGNORECASE)
    if ptr_match:
        ptr_elem = ET.SubElement(parent, p("pointer"))
        base_type_elem = ET.SubElement(ptr_elem, p("baseType"))
        build_type_node(base_type_elem, ptr_match.group(1))
        return

    string_match = re.fullmatch(r"(STRING|WSTRING)\[(.+)\]", type_text, re.IGNORECASE)
    if string_match:
        kind, length = string_match.groups()
        ET.SubElement(parent, p(kind.lower()), {"length": length.strip()})
        return

    basic_types = {
        "BOOL",
        "BYTE",
        "WORD",
        "DWORD",
        "LWORD",
        "SINT",
        "INT",
        "DINT",
        "LINT",
        "USINT",
        "UINT",
        "UDINT",
        "ULINT",
        "REAL",
        "LREAL",
        "TIME",
        "DATE",
        "DATE_AND_TIME",
        "DT",
        "TOD",
        "TIME_OF_DAY",
    }
    upper = type_text.upper()
    if upper in basic_types:
        ET.SubElement(parent, p(upper))
        return

    ET.SubElement(parent, p("derived"), {"name": type_text})


def add_pou_variable(parent: ET.Element, variable: PouVariable) -> None:
    variable_elem = ET.SubElement(parent, p("variable"), {"name": variable.name})
    type_elem = ET.SubElement(variable_elem, p("type"))
    build_type_node(type_elem, variable.type_text)

    if variable.initial_value is not None:
        initial = ET.SubElement(variable_elem, p("initialValue"))
        ET.SubElement(initial, p("simpleValue"), {"value": variable.initial_value})

    if variable.documentation:
        documentation = ET.SubElement(variable_elem, p("documentation"))
        xhtml = ET.SubElement(documentation, xhtml_tag("xhtml"))
        xhtml.text = f" {variable.documentation} "


def apply_section_attributes(elem: ET.Element, section: PouSection) -> None:
    if section.constant:
        elem.set("constant", "true")
    if section.retain:
        elem.set("retain", "true")
    if section.persistent:
        elem.set("persistent", "true")


def add_pou_inheritance(interface: ET.Element, update: PouUpdate) -> None:
    extends = (update.extends or "").strip()
    implements = [item.strip() for item in (update.implements or []) if item and item.strip()]
    if not extends and not implements:
        return

    add_data = ET.SubElement(interface, p("addData"))
    data = ET.SubElement(
        add_data,
        p("data"),
        {
            "name": "http://www.3s-software.com/plcopenxml/pouinheritance",
            "handleUnknown": "implementation",
        },
    )
    inheritance = ET.SubElement(data, p("Inheritance"))
    if extends:
        ET.SubElement(inheritance, p("Extends")).text = extends
    for item in implements:
        ET.SubElement(inheritance, p("Implements")).text = item


def update_action_element(action: ET.Element, update: PouUpdate) -> bool:
    body = find_child(action, "body")
    if body is None:
        body = ET.SubElement(action, p("body"))
    remove_children(body)
    st = ET.SubElement(body, p("ST"))
    xhtml = ET.SubElement(st, xhtml_tag("xhtml"))
    xhtml.text = "\n" + update.body + ("\n" if update.body else "")
    return True


def update_method_element(method: ET.Element, update: PouUpdate) -> bool:
    interface = find_child(method, "interface")
    if interface is None:
        interface = ET.SubElement(method, p("interface"))
    remove_children(interface)

    if update.return_type:
        return_type = ET.SubElement(interface, p("returnType"))
        build_type_node(return_type, update.return_type)

    for section in update.sections:
        xml_name = SECTION_TO_XML.get(section.kind)
        if xml_name is None or not section.variables:
            continue
        section_elem = ET.SubElement(interface, p(xml_name))
        apply_section_attributes(section_elem, section)
        for variable in section.variables:
            add_pou_variable(section_elem, variable)

    body = find_child(method, "body")
    if body is None:
        body = ET.SubElement(method, p("body"))
    remove_children(body)
    st = ET.SubElement(body, p("ST"))
    xhtml = ET.SubElement(st, xhtml_tag("xhtml"))
    xhtml.text = "\n" + update.body + ("\n" if update.body else "")
    return True


def update_pou_element(pou: ET.Element, update: PouUpdate) -> bool:
    if pou.get("pouType", "") != update.pou_type:
        return False

    interface = find_child(pou, "interface")
    if interface is None:
        interface = ET.SubElement(pou, p("interface"))
    remove_children(interface)

    if update.pou_type == "function" and update.return_type:
        return_type = ET.SubElement(interface, p("returnType"))
        build_type_node(return_type, update.return_type)

    add_pou_inheritance(interface, update)

    for section in update.sections:
        xml_name = SECTION_TO_XML.get(section.kind)
        if xml_name is None or not section.variables:
            continue
        section_elem = ET.SubElement(interface, p(xml_name))
        apply_section_attributes(section_elem, section)
        for variable in section.variables:
            add_pou_variable(section_elem, variable)

    body = find_child(pou, "body")
    if body is None:
        body = ET.SubElement(pou, p("body"))
    remove_children(body)
    st = ET.SubElement(body, p("ST"))
    xhtml = ET.SubElement(st, xhtml_tag("xhtml"))
    xhtml.text = "\n" + update.body + ("\n" if update.body else "")
    return True


def update_global_vars_element(global_vars: ET.Element, update: PouUpdate) -> bool:
    if update.pou_type != "globalVars":
        return False
    if global_vars.get("name", "") != update.name:
        return False

    add_data = find_child(global_vars, "addData")
    remove_children(global_vars)

    global_sections = [section for section in update.sections if section.kind == "VAR_GLOBAL"]
    if global_sections:
        merged = PouSection(
            kind="VAR_GLOBAL",
            variables=[variable for section in global_sections for variable in section.variables],
            retain=any(section.retain for section in global_sections),
            persistent=any(section.persistent for section in global_sections),
            constant=any(section.constant for section in global_sections),
        )
        apply_section_attributes(global_vars, merged)
        variables = merged.variables
    else:
        variables = []

    for variable in variables:
        add_pou_variable(global_vars, variable)

    if add_data is not None:
        global_vars.append(add_data)
    return True


def create_object_id_add_data(parent: ET.Element) -> str:
    add_data = find_child(parent, "addData")
    if add_data is None:
        add_data = ET.SubElement(parent, p("addData"))

    data = ET.SubElement(
        add_data,
        p("data"),
        {"name": ADDDATA_OBJECTID, "handleUnknown": "discard"},
    )
    object_id = str(uuid.uuid4())
    ET.SubElement(data, p("ObjectId")).text = object_id
    return object_id


def create_global_vars_element(update: PouUpdate) -> ET.Element:
    global_vars = ET.Element(p("globalVars"), {"name": update.name})
    global_sections = [section for section in update.sections if section.kind == "VAR_GLOBAL"]
    merged = PouSection(
        kind="VAR_GLOBAL",
        variables=[variable for section in global_sections for variable in section.variables],
        retain=any(section.retain for section in global_sections),
        persistent=any(section.persistent for section in global_sections),
        constant=any(section.constant for section in global_sections),
    )
    apply_section_attributes(global_vars, merged)
    for variable in merged.variables:
        add_pou_variable(global_vars, variable)
    create_object_id_add_data(global_vars)
    return global_vars


def ensure_resource_add_data(resource: ET.Element) -> ET.Element:
    add_data = find_child(resource, "addData")
    if add_data is None:
        add_data = ET.SubElement(resource, p("addData"))
    return add_data


def ensure_pous_element(root: ET.Element) -> ET.Element:
    pous = root.find(f".//{p('pous')}")
    if pous is not None:
        return pous
    types = root.find(f".//{p('types')}")
    if types is None:
        types = ET.SubElement(root, p("types"))
    return ET.SubElement(types, p("pous"))


def create_pou_element(update: PouUpdate) -> ET.Element:
    pou = ET.Element(p("pou"), {"name": update.name, "pouType": update.pou_type})
    update_pou_element(pou, update)
    create_object_id_add_data(pou)
    return pou


def build_data_type_base_type(parent: ET.Element, update: DataTypeUpdate) -> None:
    base_type = ET.SubElement(parent, p("baseType"))
    if update.kind == "enum":
        enum = ET.SubElement(base_type, p("enum"))
        values = ET.SubElement(enum, p("values"))
        for enum_value in update.enum_values:
            ET.SubElement(values, p("value"), {"name": enum_value.name})
        return

    struct = ET.SubElement(base_type, p("struct"))
    for field in update.fields:
        add_pou_variable(struct, field)


def create_data_type_element(update: DataTypeUpdate) -> ET.Element:
    data_type = ET.Element(p("dataType"), {"name": update.name})
    build_data_type_base_type(data_type, update)
    create_object_id_add_data(data_type)
    return data_type


def ensure_data_types_element(root: ET.Element) -> ET.Element:
    types = root.find(f".//{p('types')}")
    if types is None:
        types = ET.SubElement(root, p("types"))
    data_types = types.find(f"./{p('dataTypes')}")
    if data_types is None:
        data_types = ET.SubElement(types, p("dataTypes"))
    return data_types


def create_global_vars_data_element(update: PouUpdate) -> ET.Element:
    data = ET.Element(
        p("data"), {"name": "http://www.3s-software.com/plcopenxml/globalvars", "handleUnknown": "implementation"}
    )
    data.append(create_global_vars_element(update))
    return data


def ensure_root_add_data(root: ET.Element) -> ET.Element:
    add_data = root.find(f"./{p('addData')}")
    if add_data is None:
        add_data = ET.SubElement(root, p("addData"))
    return add_data


def find_application_resource(root: ET.Element) -> ET.Element | None:
    for resource in root.findall(f".//{p('resource')}"):
        if resource.get("name") == "Application":
            return resource
    return root.find(f".//{p('resource')}")


def create_missing_pou_objects(
    root: ET.Element, pou_updates_by_name: dict[str, PouUpdate], data_type_updates_by_name: dict[str, DataTypeUpdate]
) -> int:
    resource = find_application_resource(root)
    library_mode = resource is None
    existing_global_vars = {element.get("name", "") for element in root.findall(f".//{p('globalVars')}")}
    existing_pous = {element.get("name", "") for element in root.findall(f".//{p('pou')}")}
    existing_data_types = {element.get("name", "") for element in root.findall(f".//{p('dataType')}")}
    inserted = 0

    resource_add_data = ensure_resource_add_data(resource) if resource is not None else None
    root_add_data = ensure_root_add_data(root) if library_mode else None
    resource_children = list(resource) if resource is not None else []
    insert_index = (
        resource_children.index(resource_add_data)
        if resource is not None and resource_add_data in resource_children
        else len(resource_children)
    )
    pous_container = ensure_pous_element(root)
    data_types_container = ensure_data_types_element(root)

    for name in sorted(pou_updates_by_name):
        update = pou_updates_by_name[name]
        if update.pou_type == "globalVars":
            if name in existing_global_vars:
                continue
            if library_mode:
                root_add_data.append(create_global_vars_data_element(update))
            else:
                resource.insert(insert_index, create_global_vars_element(update))
                insert_index += 1
            existing_global_vars.add(name)
            inserted += 1
            continue

        if name in existing_pous:
            continue
        # Skip Actions and Methods - they should be children of other POUs
        if update.pou_type in {"action", "method"}:
            continue
        print(f"Creating missing POU: {name}")
        pous_container.append(create_pou_element(update))
        existing_pous.add(name)
        inserted += 1

    if data_type_updates_by_name:
        for name in sorted(data_type_updates_by_name):
            if name in existing_data_types:
                continue
            print(f"Creating missing DataType: {name}")
            data_types_container.append(create_data_type_element(data_type_updates_by_name[name]))
            existing_data_types.add(name)
            inserted += 1

    return inserted


def mapping_text(name: str) -> str:
    normalized = re.sub(r"^\s*Application\.", "", name).strip()
    normalized = re.sub(r"^\s*VAR_GLOBAL\b", "", normalized).strip()
    normalized = re.sub(r"\s+", " ", normalized)

    if normalized.startswith("Application."):
        normalized = normalized[len("Application.") :]

    if normalized.startswith("GVL_IO_Mapping."):
        return f"Application.{normalized}"
    if "." in normalized:
        return f"Application.{normalized}"
    return f"Application.GVL_IO_Mapping.{normalized}"


def build_object_path_map(root: ET.Element) -> dict[str, str]:
    project_structure = get_project_structure(root)
    if project_structure is None:
        return {}

    result: dict[str, str] = {}

    def walk(node: ET.Element, current_parts: list[str]) -> None:
        if not isinstance(node.tag, str):
            return

        tag_name = local_name(node.tag)
        if tag_name == "Folder":
            folder_name = sanitize(node.get("Name", "unnamed"))
            next_parts = [*current_parts, folder_name]
            for child in node:
                walk(child, next_parts)
            return

        if tag_name != "Object":
            return

        node_name = node.get("Name", "")
        child_parts = list(current_parts)
        if node_name == "Kbus":
            child_parts.append("kbus")
        elif current_parts == [] and node_name not in {"Device", "Application", "Kbus"}:
            child_parts.append("Fieldbus")

        obj_id = node.get("ObjectId")
        if obj_id:
            filename = f"{sanitize(node_name)}.st"
            result[obj_id] = "/".join([*child_parts, filename]) if child_parts else filename

        for child in node:
            walk(child, child_parts)

    for child in project_structure:
        walk(child, [])
    return result


def build_named_object_id_map(root: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}

    for pou in root.findall(f".//{p('pou')}"):
        obj_id = get_object_id(pou)
        name = pou.get("name", "")
        if obj_id and name:
            result[name] = obj_id

    for data_type in root.findall(f".//{p('dataType')}"):
        obj_id = get_object_id(data_type)
        name = data_type.get("name", "")
        if obj_id and name:
            result[name] = obj_id

    for configuration in root.findall(f".//{p('configuration')}"):
        obj_id = get_object_id(configuration)
        name = configuration.get("name", "")
        if obj_id and name:
            result[name] = obj_id

    for global_vars in root.findall(f".//{p('globalVars')}"):
        obj_id = get_object_id(global_vars)
        name = global_vars.get("name", "")
        if obj_id and name:
            result[name] = obj_id

    return result


def find_structure_object(root: ET.Element, target_name: str) -> ET.Element | None:
    project_structure = get_project_structure(root)
    if project_structure is None:
        return None

    for node in project_structure.iter():
        if isinstance(node.tag, str) and local_name(node.tag) == "Object" and node.get("Name") == target_name:
            return node
    return None


def ensure_folder_node(parent: ET.Element, folder_name: str) -> ET.Element:
    for child in parent:
        if isinstance(child.tag, str) and local_name(child.tag) == "Folder" and child.get("Name") == folder_name:
            return child
    return ET.SubElement(parent, "Folder", {"Name": folder_name})


def remove_managed_objects(container: ET.Element, managed_stems: set[str]) -> None:
    """Recursively remove Object nodes whose Name is in managed_stems, then prune empty folders."""
    for child in list(container):
        if not isinstance(child.tag, str):
            continue
        tag_name = local_name(child.tag)
        if tag_name == "Object" and child.get("Name", "") in managed_stems:
            container.remove(child)
        elif tag_name == "Folder":
            remove_managed_objects(child, managed_stems)
            if len(child) == 0:
                container.remove(child)


def find_object_node(parent: ET.Element, name: str, object_id: str) -> ET.Element | None:
    for child in parent:
        if not isinstance(child.tag, str) or local_name(child.tag) != "Object":
            continue
        if child.get("ObjectId") == object_id:
            return child
        if child.get("Name") == name:
            return child
    return None


def object_exists_in_tree(container: ET.Element, name: str, object_id: str) -> bool:
    for child in container.iter():
        if not isinstance(child.tag, str) or local_name(child.tag) != "Object":
            continue
        if child.get("ObjectId") == object_id:
            return True
        if child.get("Name") == name:
            return True
    return False


def rebuild_container_from_files(
    container: ET.Element, file_paths: list[Path], base_dir: Path, object_ids: dict[str, str], skip_stems: set[str] | None = None
) -> None:
    skip = skip_stems or set()

    for path in sorted(file_paths):
        stem = path.stem
        if stem in skip:
            continue
        obj_id = object_ids.get(stem)
        if obj_id is None:
            continue

        current_parent = container
        rel_parent = path.relative_to(base_dir).parent
        for part in rel_parent.parts:
            if part in {"", "."}:
                continue
            current_parent = ensure_folder_node(current_parent, sanitize(part))

        if object_exists_in_tree(container, stem, obj_id):
            continue

        existing = find_object_node(current_parent, stem, obj_id)
        if existing is None:
            ET.SubElement(current_parent, "Object", {"Name": stem, "ObjectId": obj_id})


def rebuild_project_structure_from_st(root: ET.Element, st_dir: Path, kbus_dir: Path, fieldbus_dir: Path) -> None:
    if not st_dir.exists():
        return

    object_ids = build_named_object_id_map(root)
    config_names = {cfg.get("name", "") for cfg in root.findall(f".//{p('configuration')}")}

    application = find_structure_object(root, "Application")
    project_structure = get_project_structure(root)
    application_container = application if application is not None else project_structure
    if application_container is not None:
        app_files = [
            path
            for path in st_dir.rglob("*.st")
            if path.is_file()
            and not (kbus_dir.exists() and kbus_dir in path.parents)
            and not (fieldbus_dir.exists() and fieldbus_dir in path.parents)
            and path.stem not in config_names
        ]
        rebuild_container_from_files(application_container, app_files, st_dir, object_ids)

    kbus = find_structure_object(root, "Kbus")
    if kbus is not None and kbus_dir.exists():
        kbus_files = [path for path in kbus_dir.rglob("*.st") if path.is_file()]
        rebuild_container_from_files(kbus, kbus_files, kbus_dir, object_ids, skip_stems={"Kbus"})

    device = find_structure_object(root, "Device")
    if device is not None and fieldbus_dir.exists():
        fieldbus_files = [path for path in fieldbus_dir.rglob("*.st") if path.is_file()]
        rebuild_container_from_files(device, fieldbus_files, fieldbus_dir, object_ids, skip_stems={"Device"})


def detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def restore_device_namespaces(original_text: str, serialized_xml: str) -> str:
    original_device_tags = re.findall(r"<Device\b[^>]*>", original_text)
    updated_device_tags = re.findall(r"<Device\b[^>]*>", serialized_xml)

    if not original_device_tags or len(original_device_tags) != len(updated_device_tags):
        return serialized_xml

    replacement_iter = iter(original_device_tags)
    return re.sub(r"<Device\b[^>]*>", lambda _match: next(replacement_iter), serialized_xml)


def restore_xhtml_namespace_style(original_text: str, serialized_xml: str) -> str:
    if 'xmlns:xhtml="http://www.w3.org/1999/xhtml"' in original_text:
        return serialized_xml

    serialized_xml = serialized_xml.replace(' xmlns:xhtml="http://www.w3.org/1999/xhtml"', "")
    serialized_xml = serialized_xml.replace("<xhtml:xhtml", '<xhtml xmlns="http://www.w3.org/1999/xhtml"')
    serialized_xml = serialized_xml.replace("</xhtml:xhtml>", "</xhtml>")
    return serialized_xml


def write_preserving_codesys_shape(root: ET.Element, original_bytes: bytes, output_path: Path) -> None:
    had_bom = original_bytes.startswith(b"\xef\xbb\xbf")
    original_text = original_bytes.decode("utf-8-sig")
    newline = detect_newline(original_text)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    serialized_body = ET.tostring(root, encoding="unicode")
    serialized_xml = f'<?xml version="1.0" encoding="utf-8"?>{newline}{serialized_body}'
    serialized_xml = restore_device_namespaces(original_text, serialized_xml)
    serialized_xml = restore_xhtml_namespace_style(original_text, serialized_xml)
    serialized_xml = normalize_newlines(serialized_xml).replace("\n", newline)

    output_path.write_bytes(serialized_xml.encode("utf-8-sig" if had_bom else "utf-8"))


def update_bitfield_parameter(parameter: ET.Element, variables: list[StVariable]) -> int:
    mapping = ensure_mapping(parameter)
    elements = iter_children(mapping, "Element")
    bool_variables = [var for var in variables if var.type_name.upper() == "BOOL"]
    value = find_child(parameter, "Value")
    if value is not None:
        value_elements = sorted(
            (child for child in list(value) if local_name(child.tag) == "Element"),
            key=lambda elem: (
                int(BIT_INDEX_RE.search(elem.get("name", "")).group("bit"))
                if BIT_INDEX_RE.search(elem.get("name", ""))
                else 9999
            ),
        )
        existing_names = {elem.get("name", "") for elem in elements}
        required_count = max(len(bool_variables), len(elements))
        for child in value_elements:
            if len(elements) >= required_count:
                break
            child_name = child.get("name", "")
            if child_name in existing_names:
                continue
            new_elem = ET.SubElement(mapping, "Element")
            if child_name:
                new_elem.set("name", child_name)
            new_elem.text = ""
            elements.append(new_elem)
            existing_names.add(child_name)

    sorted_elements = sorted(
        elements,
        key=lambda elem: (
            int(BIT_INDEX_RE.search(elem.get("name", "")).group("bit"))
            if BIT_INDEX_RE.search(elem.get("name", ""))
            else 9999
        ),
    )
    sorted_vars = sorted(bool_variables, key=lambda var: sort_addr(var.address))
    count = min(len(sorted_elements), len(sorted_vars))
    for elem, var in zip(sorted_elements[:count], sorted_vars[:count]):
        elem.text = mapping_text(var.name)
    return count


def update_scalar_parameters(parameters: list[ET.Element], variables: list[StVariable]) -> int:
    sorted_params = [param for param in parameters if PARAM_ID_RE.match(param.get("ParameterId", ""))]
    sorted_params.sort(key=lambda param: int(param.get("ParameterId", "0")))
    sorted_vars = sorted(
        (var for var in variables if var.type_name.upper() != "BOOL"), key=lambda var: sort_addr(var.address)
    )
    count = min(len(sorted_params), len(sorted_vars))
    for param, var in zip(sorted_params[:count], sorted_vars[:count]):
        set_text_child(param, "Name", var.name)
        set_text_child(param, "Description", var.comment or var.name)
        mapping = ensure_mapping(param)
        mapping.text = mapping_text(var.name)
        value = find_child(param, "Value")
        if value is None:
            value = ET.SubElement(param, "Value")
        value.set("visiblename", var.name)
        if var.comment:
            value.set("desc", var.comment)
    return count


def update_configuration(configuration: ET.Element, variables: list[StVariable]) -> tuple[int, int]:
    device = None
    for element in configuration.iter():
        if isinstance(element.tag, str) and local_name(element.tag) == "Device":
            device = element
            break
    if device is None:
        return 0, 0

    parameters = [
        element
        for element in device.iter()
        if isinstance(element.tag, str) and local_name(element.tag) == "Parameter"
    ]
    bitfield_count = 0
    scalar_count = 0

    bitfield_parameters: list[ET.Element] = []
    scalar_parameters: list[ET.Element] = []

    for param in parameters:
        param_type = param.get("type", "")
        if param_type.endswith("InputField") or param_type.endswith("OutputField"):
            bitfield_parameters.append(param)
        elif param_type in {
            "std:BOOL",
            "std:BYTE",
            "std:WORD",
            "std:DWORD",
            "std:LWORD",
            "std:SINT",
            "std:INT",
            "std:DINT",
            "std:LINT",
            "std:USINT",
            "std:UINT",
            "std:UDINT",
            "std:ULINT",
            "std:REAL",
            "std:LREAL",
            "std:TIME",
        }:
            scalar_parameters.append(param)

    for param in bitfield_parameters:
        bitfield_count += update_bitfield_parameter(param, variables)
    scalar_count += update_scalar_parameters(scalar_parameters, variables)
    return bitfield_count, scalar_count


def update_fieldbus_scalar_parameters(parameters: list[ET.Element], variables: list[FieldbusVariableUpdate]) -> int:
    simple_parameters = []
    for param in parameters:
        if param.get("FixedAddress"):
            continue
        value = find_child(param, "Value")
        if value is not None and iter_children(value, "Element"):
            continue
        simple_parameters.append(param)

    parameter_type_keys = [fieldbus_type_key(param.get("type", "")) for param in simple_parameters]
    variable_type_keys = [fieldbus_type_key(var.type_name) for var in variables]
    matches = longest_common_subsequence(parameter_type_keys, variable_type_keys)

    count = 0
    for param_index, var_index in matches:
        param = simple_parameters[param_index]
        var = variables[var_index]
        set_text_child(param, "Name", var.name)
        value = find_child(param, "Value")
        if value is None:
            value = ET.SubElement(param, "Value")
        value.set("visiblename", var.name)
        if var.mapping:
            mapping = ensure_mapping(param)
            mapping.text = var.mapping
        count += 1
    return count


def update_fieldbus_configuration(configuration: ET.Element, variables: list[FieldbusVariableUpdate]) -> int:
    device = None
    for element in configuration.iter():
        if isinstance(element.tag, str) and local_name(element.tag) == "Device":
            device = element
            break
    if device is None:
        return 0

    parameters = [
        element
        for element in device.iter()
        if isinstance(element.tag, str) and local_name(element.tag) == "Parameter"
    ]
    return update_fieldbus_scalar_parameters(parameters, variables)


def update_pous(
    root: ET.Element, pou_updates_by_name: dict[str, PouUpdate], pou_updates_by_path: dict[str, PouUpdate]
) -> int:
    updated_count = 0
    object_path_map = build_object_path_map(root)
    for pou in root.findall(f".//{p('pou')}"):
        update = None
        obj_id = get_object_id(pou)
        pou_relpath = None
        if obj_id:
            pou_relpath = object_path_map.get(obj_id)
            if pou_relpath:
                update = pou_updates_by_path.get(pou_relpath)
        if update is None:
            name = pou.get("name", "")
            update = pou_updates_by_name.get(name)
        if update is not None:
            if update_pou_element(pou, update):
                updated_count += 1

        # Handle nested Actions and Methods
        pou_name = pou.get("name", "")
        # Fallback to name-based directory if relpath is missing
        if pou_relpath:
            pou_dir = pou_relpath[:-3] # Remove ".st"
        else:
            pou_dir = pou_name

        # Actions
        actions_container = find_child(pou, "actions")
        for action in iter_children(actions_container, "action"):
            action_name = action.get("name")
            # Try both relative path and name-only path for action
            action_relpath = f"{pou_dir}/{action_name}.st"
            action_update = pou_updates_by_path.get(action_relpath) or pou_updates_by_name.get(action_name)
            
            if action_update and update_action_element(action, action_update):
                updated_count += 1
            
        # Methods
        methods_container = find_child(pou, "methods")
        for method in iter_children(methods_container, "method"):
            method_name = method.get("name")
            method_relpath = f"{pou_dir}/{method_name}.st"
            method_update = pou_updates_by_path.get(method_relpath) or pou_updates_by_name.get(method_name)
            
            if method_update and update_method_element(method, method_update):
                updated_count += 1

    for global_vars in root.findall(f".//{p('globalVars')}"):
        update = None
        obj_id = get_object_id(global_vars)
        if obj_id:
            relpath = object_path_map.get(obj_id)
            if relpath:
                update = pou_updates_by_path.get(relpath)
        if update is None:
            name = global_vars.get("name", "")
            update = pou_updates_by_name.get(name)
        if update is None:
            continue
        if update_global_vars_element(global_vars, update):
            updated_count += 1
    return updated_count


def update_data_type_element(data_type: ET.Element, update: DataTypeUpdate) -> bool:
    if data_type.get("name", "") != update.name:
        return False

    add_data = find_child(data_type, "addData")
    remove_children(data_type)
    build_data_type_base_type(data_type, update)
    if add_data is not None:
        data_type.append(add_data)
    return True


def update_data_types(
    root: ET.Element,
    data_type_updates_by_name: dict[str, DataTypeUpdate],
    data_type_updates_by_path: dict[str, DataTypeUpdate],
) -> int:
    updated_count = 0
    object_path_map = build_object_path_map(root)
    for data_type in root.findall(f".//{p('dataType')}"):
        update = None
        obj_id = get_object_id(data_type)
        if obj_id:
            relpath = object_path_map.get(obj_id)
            if relpath:
                update = data_type_updates_by_path.get(relpath)
        if update is None:
            update = data_type_updates_by_name.get(data_type.get("name", ""))
        if update is None:
            continue
        if update_data_type_element(data_type, update):
            updated_count += 1
    return updated_count


class ProjectInserter:
    def __init__(self, xml_path: Path):
        self.xml_path = xml_path
        self.original_bytes = xml_path.read_bytes()
        self.root = ET.fromstring(self.original_bytes.decode("utf-8-sig"))

    def insert(
        self,
        st_dir: Path,
        kbus_dir: Path | None = None,
        fieldbus_dir: Path | None = None,
        output_path: Path | None = None,
    ) -> dict[str, int]:
        kbus_dir = kbus_dir or st_dir / "kbus"
        fieldbus_dir = fieldbus_dir or st_dir / "Fieldbus"
        output_path = output_path or self.xml_path.with_name(f"{self.xml_path.stem}_updated.xml")

        kbus_variables = load_kbus_variables(kbus_dir)
        fieldbus_variables = load_fieldbus_variables(fieldbus_dir)
        pou_updates_by_name, pou_updates_by_path = (
            load_pou_updates(st_dir, exclude_dirs=[kbus_dir, fieldbus_dir])
            if st_dir and st_dir.exists()
            else ({}, {})
        )
        data_type_updates_by_name, data_type_updates_by_path = (
            load_data_type_updates(st_dir, exclude_dirs=[kbus_dir, fieldbus_dir])
            if st_dir and st_dir.exists()
            else ({}, {})
        )

        configuration_names = [cfg.get("name", "") for cfg in self.root.findall(f".//{p('configuration')}")]
        assigned_variables = build_variable_assignment(configuration_names, kbus_variables)

        updated_configs: set[str] = set()
        updated_bitfields = 0
        updated_scalars = 0
        updated_fieldbus_scalars = 0

        created_objects = create_missing_pou_objects(self.root, pou_updates_by_name, data_type_updates_by_name)
        updated_pous = update_pous(self.root, pou_updates_by_name, pou_updates_by_path)
        updated_data_types = update_data_types(self.root, data_type_updates_by_name, data_type_updates_by_path)

        for configuration in self.root.findall(f".//{p('configuration')}"):
            name = configuration.get("name", "")
            variables = assigned_variables.get(name)
            if variables:
                bitfields, scalars = update_configuration(configuration, variables)
                if bitfields or scalars:
                    updated_configs.add(name)
                    updated_bitfields += bitfields
                    updated_scalars += scalars

            fieldbus_update = fieldbus_variables.get(name)
            if fieldbus_update:
                fieldbus_scalars = update_fieldbus_configuration(configuration, fieldbus_update)
                if fieldbus_scalars:
                    updated_configs.add(name)
                    updated_fieldbus_scalars += fieldbus_scalars

        rebuild_project_structure_from_st(self.root, st_dir, kbus_dir, fieldbus_dir)
        write_preserving_codesys_shape(self.root, self.original_bytes, output_path)

        return {
            "created_objects": created_objects,
            "updated_pous": updated_pous,
            "updated_data_types": updated_data_types,
            "updated_configs": len(updated_configs),
            "updated_bitfields": updated_bitfields,
            "updated_scalars": updated_scalars,
            "updated_fieldbus_scalars": updated_fieldbus_scalars,
            "output_path": str(output_path.resolve()),
        }
