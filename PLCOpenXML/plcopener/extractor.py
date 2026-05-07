from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from .xml_utils import (
    ADDDATA_UNION,
    NS_XHTML,
    find_child,
    get_element_text,
    get_object_id,
    get_project_structure,
    iter_children,
    local_name,
    p,
    sanitize,
)

VARIABLE_SECTIONS = (
    ("inputVars", "VAR_INPUT"),
    ("outputVars", "VAR_OUTPUT"),
    ("inOutVars", "VAR_IN_OUT"),
    ("localVars", "VAR"),
    ("tempVars", "VAR_TEMP"),
    ("externalVars", "VAR_EXTERNAL"),
    ("globalVars", "VAR_GLOBAL"),
)
SECTION_KEYWORDS = dict(VARIABLE_SECTIONS)

POU_KEYWORDS = {
    "functionBlock": "FUNCTION_BLOCK",
    "function": "FUNCTION",
    "program": "PROGRAM",
}


def parse_xml(xml_path: Path) -> ET.Element:
    return ET.parse(xml_path).getroot()


def normalize_inline_text(value: str) -> str:
    return " ".join(value.split())


def normalize_identifier(value: str) -> str:
    """Convert arbitrary names into a readable ST identifier."""
    value = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value.strip())
    value = "_".join(part for part in value.split("_") if part)
    if not value:
        return "unnamed"
    if value[0].isdigit():
        value = "_" + value
    return value


def sanitize_array_bound(value: str, fallback: str = "?") -> str:
    value = (value or "").strip()
    if not value:
        return fallback
    if value.lstrip("+-").isdigit():
        return value
    if "ERROR" in value.upper():
        return "32"
    return value


def render_parameter_type(type_name: str | None) -> str:
    """Render device parameter type strings into readable ST syntax."""
    value = (type_name or "").strip()
    if not value:
        return "WORD"

    if ":" in value:
        _, value = value.split(":", 1)
    value = value.strip()
    upper_value = value.upper()

    if upper_value.startswith("ARRAY"):
        return value

    if upper_value.startswith("STRING(") and value.endswith(")"):
        return f"STRING[{value[len('STRING('):-1]}]"
    if upper_value.startswith("WSTRING(") and value.endswith(")"):
        return f"WSTRING[{value[len('WSTRING('):-1]}]"

    return upper_value


def render_parameter_initial_value(parameter: ET.Element) -> str:
    value_elem = find_child(parameter, "Value")
    if value_elem is None:
        return ""

    value_text = normalize_inline_text(get_element_text(value_elem))
    if not value_text:
        return ""

    if iter_children(value_elem, "Element"):
        return f" := {value_text}"

    return f" := {value_text}"


def configuration_child_configs(configuration: ET.Element) -> list[ET.Element]:
    add_data = find_child(configuration, "addData")
    for data in iter_children(add_data, "data"):
        if data.get("name") != "configurations":
            continue
        configurations = find_child(data, "configurations")
        if configurations is None:
            continue
        return iter_children(configurations, "configuration")
    return []


def extract_st_body(pou: ET.Element) -> str | None:
    """Return the raw ST body text, or None if the POU is not ST-based."""
    body = find_child(pou, "body")
    st = find_child(body, "ST")
    if st is None:
        return None

    xhtml = st.find(f"{{{NS_XHTML}}}xhtml")
    if xhtml is None:
        xhtml = st.find("xhtml")
    if xhtml is None:
        return None

    text = get_element_text(xhtml)
    if not text:
        return ""
    return text.lstrip("\r\n").rstrip()


def render_type(type_elem: ET.Element | None) -> str:
    """Render a PLCOpen <type> or <baseType> node into ST syntax."""
    if type_elem is None:
        return "UNKNOWN"

    type_children = [child for child in list(type_elem) if isinstance(child.tag, str)]
    if not type_children:
        return "UNKNOWN"

    node = type_children[0]
    node_name = local_name(node.tag)

    if node_name == "derived":
        return node.get("name", "UNKNOWN")

    if node_name == "array":
        dims = []
        for dim in iter_children(node, "dimension"):
            lower = sanitize_array_bound(dim.get("lower", "?"))
            upper = sanitize_array_bound(dim.get("upper", "?"))
            dims.append(f"{lower}..{upper}")
        base_type = render_type(find_child(node, "baseType"))
        return f"ARRAY [{', '.join(dims)}] OF {base_type}"

    if node_name == "pointer":
        return f"POINTER TO {render_type(find_child(node, 'baseType'))}"

    if node_name in {"string", "wstring"}:
        length = node.get("length")
        if length:
            return f"{node_name.upper()}[{length}]"
        return node_name.upper()

    if node_name in {"struct", "enum"}:
        return node_name.upper()

    if node_name in {"subrangeSigned", "subrangeUnsigned"}:
        base = node.get("baseType")
        lower = node.get("lower")
        upper = node.get("upper")
        if base and lower and upper:
            return f"{base} ({lower}..{upper})"
        return node_name

    return node_name


def render_initial_value(variable: ET.Element) -> str:
    initial = find_child(variable, "initialValue")
    if initial is None:
        return ""

    simple = find_child(initial, "simpleValue")
    if simple is not None:
        value = simple.get("value")
        if value is not None:
            return f" := {value}"

    values = normalize_inline_text(get_element_text(initial))
    if values:
        return f" := {values}"
    return ""


def render_documentation(variable: ET.Element) -> str:
    documentation = find_child(variable, "documentation")
    if documentation is None:
        return ""

    xhtml = documentation.find(f"{{{NS_XHTML}}}xhtml")
    if xhtml is None:
        xhtml = documentation.find("xhtml")
    text = normalize_inline_text(get_element_text(xhtml))
    return text


def render_variable(variable: ET.Element) -> str:
    name = variable.get("name", "unnamed")
    type_str = render_type(find_child(variable, "type"))
    initial_value = render_initial_value(variable)
    line = f"\t{name} : {type_str}{initial_value};"

    doc = render_documentation(variable)
    if doc:
        line += f" (* {doc} *)"
    return line


def render_section_header(section: ET.Element, base_keyword: str) -> str:
    qualifiers: list[str] = []
    if section.get("constant", "").lower() == "true":
        qualifiers.append("CONSTANT")
    if section.get("retain", "").lower() == "true":
        qualifiers.append("RETAIN")
    if section.get("persistent", "").lower() == "true":
        qualifiers.append("PERSISTENT")
    if qualifiers:
        return f"{base_keyword} {' '.join(qualifiers)}"
    return base_keyword


def render_global_vars_source(global_vars: ET.Element) -> str:
    name = global_vars.get("name", "unknown")
    lines: list[str] = []

    add_data = find_child(global_vars, "addData")
    for data in iter_children(add_data, "data"):
        if data.get("name") != "http://www.3s-software.com/plcopenxml/attributes":
            continue
        attributes = find_child(data, "Attributes")
        if attributes is None:
            continue
        for attribute in iter_children(attributes, "Attribute"):
            attr_name = attribute.get("Name", "").strip()
            if not attr_name:
                continue
            attr_value = attribute.get("Value", "")
            if attr_value:
                lines.append(f"{{attribute '{attr_name}' := '{attr_value}'}}")
            else:
                lines.append(f"{{attribute '{attr_name}'}}")

    lines.append(render_section_header(global_vars, "VAR_GLOBAL"))
    lines.extend(render_variable(variable) for variable in iter_children(global_vars, "variable"))
    lines.append("END_VAR")
    lines.append("")
    return "\n".join(lines)


def render_interface(pou: ET.Element) -> list[str]:
    interface = find_child(pou, "interface")
    if interface is None:
        return []

    lines: list[str] = []
    for section in [child for child in list(interface) if isinstance(child.tag, str)]:
        section_name = local_name(section.tag)
        st_section = SECTION_KEYWORDS.get(section_name)
        if st_section is None:
            continue

        variables = iter_children(section, "variable")
        if not variables:
            continue
        if lines:
            lines.append("")
        lines.append(render_section_header(section, st_section))
        lines.extend(render_variable(variable) for variable in variables)
        lines.append("END_VAR")

    return lines


def render_base_type_definition(base_type: ET.Element | None, end_keyword: str = "END_STRUCT") -> list[str]:
    if base_type is None:
        return ["UNKNOWN"]

    children = [child for child in list(base_type) if isinstance(child.tag, str)]
    if not children:
        return ["UNKNOWN"]

    node = children[0]
    node_name = local_name(node.tag)

    if node_name == "struct":
        lines = ["STRUCT"]
        lines.extend(render_variable(variable) for variable in iter_children(node, "variable"))
        lines.append(end_keyword)
        return lines

    return [f"{render_type(base_type)};"]


def render_data_type_source(data_type: ET.Element) -> str:
    name = data_type.get("name", "unknown")
    lines = [f"TYPE {name} :"]
    lines.extend(render_base_type_definition(find_child(data_type, "baseType")))
    lines.append("END_TYPE")
    lines.append("")
    return "\n".join(lines)


def render_union_source(union: ET.Element) -> str:
    name = union.get("name", "unknown")
    lines = [f"TYPE {name} :", "UNION"]
    lines.extend(render_variable(variable) for variable in iter_children(union, "variable"))
    lines.extend(["END_UNION", "END_TYPE", ""])
    return "\n".join(lines)


def render_configuration_source(configuration: ET.Element) -> str:
    """Render a KBUS/device configuration as a readable ST-like summary."""

    def format_port_comment(element: ET.Element, fallback: str = "") -> str:
        port_name = element.get("name", "").strip()
        port_label = port_name or fallback
        if not port_label:
            return ""
        return f" (* IO port: {port_label} *)"

    def expand_mapped_bits(parameter: ET.Element, fixed_address: str) -> list[str]:
        mapping = find_child(parameter, "Mapping")
        if mapping is None:
            return []

        byte_match = None
        if fixed_address.startswith("%IB") or fixed_address.startswith("%QB"):
            byte_match = fixed_address[3:]
        if byte_match is None:
            return []

        direction = "I" if fixed_address.startswith("%IB") else "Q"
        lines_out: list[str] = []
        for element in iter_children(mapping, "Element"):
            mapping_text = get_element_text(element).strip()
            if not mapping_text:
                continue
            bit_match = element.get("name", "")
            bit_idx = None
            bit_search = bit_match.rsplit("Bit", 1)
            if len(bit_search) == 2:
                suffix = bit_search[1]
                digits = ""
                for ch in suffix:
                    if ch.isdigit():
                        digits += ch
                    else:
                        break
                if digits:
                    bit_idx = int(digits) - 1
            if bit_idx is None:
                continue
            bit_address = f"%{direction}X{byte_match}.{bit_idx}"
            comment = format_port_comment(element, bit_address)
            lines_out.append(f"\t{mapping_text} AT {bit_address} : BOOL;{comment}")
        return lines_out

    def mapped_parameter_line(parameter: ET.Element, fixed_address: str, param_type: str) -> str | None:
        mapping = find_child(parameter, "Mapping")
        if mapping is None:
            return None
        mapped_elements = iter_children(mapping, "Element")
        if len(mapped_elements) != 1:
            return None
        mapping_element = mapped_elements[0]
        mapping_text = get_element_text(mapping_element).strip()
        if not mapping_text:
            return None
        comment = format_port_comment(mapping_element, fixed_address)
        return f"\t{mapping_text} AT {fixed_address} : {param_type};{comment}"

    def unmapped_parameter_lines(parameter: ET.Element, param_type: str) -> list[str]:
        mapping = find_child(parameter, "Mapping")
        if mapping is None:
            return []

        mapped_elements = iter_children(mapping, "Element")
        if not mapped_elements:
            return []

        if len(mapped_elements) == 1:
            mapping_element = mapped_elements[0]
            mapping_text = get_element_text(mapping_element).strip()
            if not mapping_text:
                return []
            comment = format_port_comment(mapping_element)
            return [f"\t{mapping_text} : {param_type};{comment}"]

        lines_out: list[str] = []
        for element in mapped_elements:
            mapping_text = get_element_text(element).strip()
            if not mapping_text:
                continue
            comment = format_port_comment(element)
            lines_out.append(f"\t{mapping_text} : BOOL;{comment}")
        return lines_out

    def find_device(configuration_elem: ET.Element) -> ET.Element | None:
        add_data = find_child(configuration_elem, "addData")
        for data in iter_children(add_data, "data"):
            if data.get("name") != "Device":
                continue
            device = find_child(data, "Device")
            if device is not None:
                return device
            for child in data:
                if isinstance(child.tag, str) and local_name(child.tag) == "Device":
                    return child
        return None

    def normalize_scalar_param_type(param_type: str) -> str:
        allowed_types = {
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
            "STRING",
            "WSTRING",
        }
        if param_type in allowed_types:
            return param_type
        if param_type.startswith("STRING[") or param_type.startswith("WSTRING[") or param_type.startswith("ARRAY"):
            return param_type
        return "WORD"

    def scalar_mapping_text(parameter: ET.Element) -> str:
        mapping = find_child(parameter, "Mapping")
        if mapping is None:
            return ""
        mapping_text = (mapping.text or "").strip()
        if mapping_text:
            return mapping_text
        return ""

    def build_parameter_metadata(parameter: ET.Element) -> tuple[str, str, str]:
        name_elem = parameter.find("Name")
        desc_elem = parameter.find("Description")
        value_elem = parameter.find("Value")

        raw_name = ""
        if name_elem is not None and name_elem.text:
            raw_name = name_elem.text.strip()
        if value_elem is not None and value_elem.get("visiblename"):
            raw_name = value_elem.get("visiblename", "").strip() or raw_name
        if not raw_name:
            raw_name = parameter.get("ParameterId", "unnamed")

        comment_parts = []
        if name_elem is not None and name_elem.text:
            comment_parts.append(name_elem.text.strip())
        if desc_elem is not None and desc_elem.text:
            comment_parts.append(desc_elem.text.strip())
        mapping_text = scalar_mapping_text(parameter)
        if mapping_text:
            comment_parts.append(f"Mapping: {mapping_text}")

        return raw_name, normalize_identifier(raw_name), " | ".join(part for part in comment_parts if part)

    def render_scalar_parameter_line(parameter: ET.Element, indent: str) -> str | None:
        if iter_children(find_child(parameter, "Value"), "Element"):
            return None

        _, identifier, comment = build_parameter_metadata(parameter)
        param_type = normalize_scalar_param_type(render_parameter_type(parameter.get("type")))
        initial_value = render_parameter_initial_value(parameter)
        line = f"{indent}{identifier} : {param_type}{initial_value};"
        if comment:
            line += f" (* {comment} *)"
        return line

    def render_configuration_block(configuration_elem: ET.Element, depth: int = 0) -> list[str]:
        indent = "\t" * depth
        section_indent = "\t" * (depth + 1)
        name = configuration_elem.get("name", "unknown")
        device = find_device(configuration_elem)
        child_configs = configuration_child_configs(configuration_elem)

        if device is None:
            lines_local = [f"{indent}(* CONFIGURATION {name} has no device data. *)"]
            for child_cfg in child_configs:
                lines_local.append("")
                lines_local.extend(render_configuration_block(child_cfg, depth + 1))
            return lines_local

        device_id = ""
        version = ""
        identification = device.find(".//DeviceIdentification")
        if identification is not None:
            id_elem = identification.find("Id")
            ver_elem = identification.find("Version")
            if id_elem is not None and id_elem.text:
                device_id = id_elem.text.strip()
            if ver_elem is not None and ver_elem.text:
                version = ver_elem.text.strip()

        lines_local = [f"{indent}(* CONFIGURATION {name}"]
        if device_id:
            lines_local.append(f"{indent}   DeviceId: {device_id}")
        if version:
            lines_local.append(f"{indent}   Version: {version}")
        lines_local.append(f"{indent}*)")

        parameter_lines: list[str] = []
        for parameter in device.findall(".//Parameter"):
            fixed_address = parameter.get("FixedAddress")
            param_type = normalize_scalar_param_type(render_parameter_type(parameter.get("type")))
            _, identifier, comment = build_parameter_metadata(parameter)

            if not fixed_address:
                scalar_line = render_scalar_parameter_line(parameter, section_indent)
                if scalar_line is not None:
                    parameter_lines.append(scalar_line)
                else:
                    parameter_lines.extend(unmapped_parameter_lines(parameter, param_type))
                continue

            expanded_bits = expand_mapped_bits(parameter, fixed_address)
            if expanded_bits:
                parameter_lines.extend(expanded_bits)
                continue

            mapped_line = mapped_parameter_line(parameter, fixed_address, param_type)
            if mapped_line is not None:
                parameter_lines.append(mapped_line)
                continue

            line = f"{section_indent}{identifier} AT {fixed_address} : {param_type};"
            if comment:
                line += f" (* {comment} *)"
            parameter_lines.append(line)

        if parameter_lines:
            lines_local.append(f"{indent}VAR_GLOBAL")
            lines_local.extend(parameter_lines)
            lines_local.append(f"{indent}END_VAR")

        for child_cfg in child_configs:
            lines_local.append("")
            lines_local.extend(render_configuration_block(child_cfg, depth + 1))

        return lines_local

    return "\n".join([*render_configuration_block(configuration), ""])


def render_pou_source(pou: ET.Element) -> str | None:
    """Render a full ST file for a POU, including declaration and body."""
    body = extract_st_body(pou)
    if body is None:
        return None

    pou_name = pou.get("name", "unknown")
    pou_type = pou.get("pouType", "pou")
    keyword = POU_KEYWORDS.get(pou_type, pou_type.upper())
    interface = find_child(pou, "interface")

    extends_name = ""
    implements_names: list[str] = []
    interface_add_data = find_child(interface, "addData")
    for data in iter_children(interface_add_data, "data"):
        if data.get("name") != "http://www.3s-software.com/plcopenxml/pouinheritance":
            continue
        inheritance = find_child(data, "Inheritance")
        if inheritance is None:
            continue
        extends = find_child(inheritance, "Extends")
        if extends is not None:
            extends_name = normalize_inline_text(get_element_text(extends))
        for implements in iter_children(inheritance, "Implements"):
            value = normalize_inline_text(get_element_text(implements))
            if value:
                implements_names.append(value)

    header = keyword
    if pou_type == "function":
        return_type = render_type(find_child(interface, "returnType"))
        header = f"{keyword} {pou_name} : {return_type}"
    else:
        header = f"{keyword} {pou_name}"

    if extends_name:
        header += f" EXTENDS {extends_name}"
    if implements_names:
        header += f" IMPLEMENTS {', '.join(implements_names)}"

    parts = [header]
    interface_lines = render_interface(pou)
    if interface_lines:
        parts.extend(["", *interface_lines])
    parts.extend(["", body, ""])
    return "\n".join(parts)


def build_id_map(root: ET.Element) -> dict[str, dict[str, object]]:
    """
    Build {ObjectId -> {'name': str, 'pou_type': str, 'element': ET.Element}}.
    Covers both POUs and dataTypes.
    """
    id_map: dict[str, dict[str, object]] = {}

    for pou in root.findall(f".//{p('pou')}"):
        obj_id = get_object_id(pou)
        if obj_id:
            id_map[obj_id] = {
                "name": pou.get("name", "unknown"),
                "pou_type": pou.get("pouType", "pou"),
                "element": pou,
            }

    for dt in root.findall(f".//{p('dataType')}"):
        obj_id = get_object_id(dt)
        if obj_id:
            id_map[obj_id] = {
                "name": dt.get("name", "unknown"),
                "pou_type": "dataType",
                "element": dt,
            }

    project_add_data = find_child(root, "addData")
    for data in iter_children(project_add_data, "data"):
        if data.get("name") != ADDDATA_UNION:
            continue
        union = find_child(data, "union")
        if union is None:
            continue
        obj_id = get_object_id(union)
        if obj_id:
            id_map[obj_id] = {
                "name": union.get("name", "unknown"),
                "pou_type": "union",
                "element": union,
            }

    for configuration in root.findall(f".//{p('configuration')}"):
        obj_id = get_object_id(configuration)
        if obj_id:
            id_map[obj_id] = {
                "name": configuration.get("name", "unknown"),
                "pou_type": "configuration",
                "element": configuration,
            }

    for global_vars in root.findall(f".//{p('globalVars')}"):
        obj_id = get_object_id(global_vars)
        if obj_id:
            id_map[obj_id] = {
                "name": global_vars.get("name", "unknown"),
                "pou_type": "globalVars",
                "element": global_vars,
            }

    return id_map


class ProjectExtractor:
    def __init__(self, xml_path: Path):
        self.xml_path = xml_path
        self.root = parse_xml(xml_path)
        self.id_map = build_id_map(self.root)

    def write_st_file(self, info: dict[str, object], out_dir: Path) -> None:
        """Write an .st file for a supported project object."""
        element = info["element"]
        if not isinstance(element, ET.Element):
            return

        pou_type = str(info["pou_type"])
        if pou_type == "dataType":
            source = render_data_type_source(element)
        elif pou_type == "union":
            source = render_union_source(element)
        elif pou_type == "configuration":
            source = render_configuration_source(element)
        elif pou_type == "globalVars":
            source = render_global_vars_source(element)
        else:
            source = render_pou_source(element)
        if source is None:
            return

        out_dir.mkdir(parents=True, exist_ok=True)
        filename = sanitize(str(info["name"])) + ".st"
        out_path = out_dir / filename
        out_path.write_text(source, encoding="utf-8")
        print(f"  + {out_path}")

    def process_folder(
        self,
        folder_elem: ET.Element,
        out_dir: Path,
        depth: int = 0,
    ) -> None:
        """Recursively walk a <Folder> element and write .st files."""
        indent = "  " * depth
        folder_name = folder_elem.get("Name", "unnamed")
        folder_dir = out_dir / sanitize(folder_name)
        print(f"{indent}[{folder_name}]")

        for child in folder_elem:
            if not isinstance(child.tag, str):
                continue
            tag_name = local_name(child.tag)
            if tag_name == "Folder":
                self.process_folder(child, folder_dir, depth + 1)
            elif tag_name == "Object":
                obj_id = child.get("ObjectId")
                if obj_id and obj_id in self.id_map:
                    self.write_st_file(self.id_map[obj_id], folder_dir)

    def process_structure_node(
        self,
        node: ET.Element,
        out_dir: Path,
        depth: int = 0,
        parent_name: str = "",
    ) -> None:
        """Recursively walk ProjectStructure nodes, including Object containers."""
        if not isinstance(node.tag, str):
            return

        tag_name = local_name(node.tag)
        if tag_name == "Folder":
            self.process_folder(node, out_dir, depth)
            return

        if tag_name != "Object":
            return

        node_name = node.get("Name", "")
        child_out_dir = out_dir
        if node_name == "Kbus":
            child_out_dir = out_dir / "kbus"
        elif parent_name == "Device" and node_name not in {"Application", "Kbus"}:
            child_out_dir = out_dir / "Fieldbus"

        obj_id = node.get("ObjectId")
        if obj_id and obj_id in self.id_map:
            self.write_st_file(self.id_map[obj_id], child_out_dir)

        # Some project exports use container Objects like "Application" that own folders.
        for child in node:
            self.process_structure_node(child, child_out_dir, depth, node_name)

    def flat_export(self, out_dir: Path) -> None:
        """Write all ST POUs into one directory."""
        for info in self.id_map.values():
            self.write_st_file(info, out_dir)

    def extract(self, out_root: Path, flat: bool = False) -> None:
        if flat:
            print("Writing flat ST files ...")
            self.flat_export(out_root)
        else:
            project_structure = get_project_structure(self.root)
            if project_structure is not None:
                print("Recreating folder structure from ProjectStructure ...")
                for child in project_structure:
                    self.process_structure_node(child, out_root)
            else:
                print("No ProjectStructure found, falling back to flat export.")
                self.flat_export(out_root)
