import xml.etree.ElementTree as ET
from typing import List, Optional

NS = "http://www.plcopen.org/xml/tc6_0200"
NS_XHTML = "http://www.w3.org/1999/xhtml"
ADDDATA_OBJECTID = "http://www.3s-software.com/plcopenxml/objectid"
ADDDATA_PROJECTSTRUCTURE = "http://www.3s-software.com/plcopenxml/projectstructure"
ADDDATA_UNION = "http://www.3s-software.com/plcopenxml/union"

def p(tag: str) -> str:
    return f"{{{NS}}}{tag}"

def xhtml_tag(tag: str) -> str:
    return f"{{{NS_XHTML}}}{tag}"

def sanitize(name: str) -> str:
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name

def local_name(tag: str) -> str:
    return tag.split("}", 1)[-1]

def iter_children(parent: Optional[ET.Element], tag: str) -> List[ET.Element]:
    if parent is None:
        return []
    children = parent.findall(p(tag))
    if children:
        return children
    return parent.findall(tag)

def find_child(parent: Optional[ET.Element], tag: str) -> Optional[ET.Element]:
    if parent is None:
        return None
    child = parent.find(p(tag))
    if child is None:
        child = parent.find(tag)
    return child

def get_element_text(element: Optional[ET.Element]) -> str:
    if element is None:
        return ""
    return "".join(element.itertext())

def get_object_id(element: ET.Element) -> Optional[str]:
    add_data = find_child(element, "addData")
    if add_data is None:
        return None

    for data in iter_children(add_data, "data"):
        if data.get("name") != ADDDATA_OBJECTID:
            continue
        obj_id = find_child(data, "ObjectId")
        if obj_id is not None and obj_id.text:
            return obj_id.text.strip()
    return None

def set_text_child(parent: ET.Element, tag: str, value: str) -> None:
    child = find_child(parent, tag)
    if child is None:
        child = ET.SubElement(parent, tag)
    child.text = value

def remove_children(parent: ET.Element) -> None:
    for child in list(parent):
        parent.remove(child)

def get_project_structure(root: ET.Element) -> Optional[ET.Element]:
    add_data = find_child(root, "addData")
    if add_data is None:
        return None

    for data in iter_children(add_data, "data"):
        if data.get("name") != ADDDATA_PROJECTSTRUCTURE:
            continue
        return find_child(data, "ProjectStructure")
    return None
