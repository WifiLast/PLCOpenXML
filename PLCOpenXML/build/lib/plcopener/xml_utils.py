import xml.etree.ElementTree as ET
import re
from typing import List, Optional
from pathlib import Path

NS = "http://www.plcopen.org/xml/tc6_0200"
NS_XHTML = "http://www.w3.org/1999/xhtml"
ADDDATA_OBJECTID = "http://www.3s-software.com/plcopenxml/objectid"
ADDDATA_PROJECTSTRUCTURE = "http://www.3s-software.com/plcopenxml/projectstructure"
ADDDATA_UNION = "http://www.3s-software.com/plcopenxml/union"

def p(tag: str) -> str:
    return f"{{{NS}}}{tag}"

def parse_xml_resilient(xml_path: Path) -> ET.Element:
    """Attempt to parse XML, fixing truncation errors by closing open tags."""
    try:
        return ET.parse(xml_path).getroot()
    except ET.ParseError as e:
        # If it's a "no element found" or "mismatched tag" at the end, try to fix it
        print(f"Warning: XML parse failed ({e}), attempting recovery...")
        text = xml_path.read_text(encoding="utf-8")
        
        # Heuristic: Find all opening tags and see which ones are not closed
        # This is a bit simplified but works for many cases
        tags = re.findall(r'<([a-zA-Z0-9:]+)(?:\s+[^>]*[^/])?>', text)
        closing_tags = re.findall(r'</([a-zA-Z0-9:]+)>', text)
        
        # We only care about the sequence of open tags
        open_stack = []
        for t in re.finditer(r'<([a-zA-Z0-9:]+)(?:\s+[^>]*[^/])?>|</([a-zA-Z0-9:]+)>', text):
            if t.group(1): # Opening
                open_stack.append(t.group(1))
            else: # Closing
                if open_stack and open_stack[-1] == t.group(2):
                    open_stack.pop()
        
        fixed_text = text.rstrip()
        # Remove any partial tag at the very end
        if fixed_text.endswith('<') or (fixed_text.rfind('<') > fixed_text.rfind('>')):
            fixed_text = fixed_text[:fixed_text.rfind('<')]
            
        for tag in reversed(open_stack):
            fixed_text += f"</{tag}>"
            
        try:
            return ET.fromstring(fixed_text)
        except ET.ParseError as e2:
            print(f"Recovery failed: {e2}")
            raise e

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

def get_all_resources(root: ET.Element) -> List[ET.Element]:
    """Find all resource elements in the project."""
    return root.findall(f".//{p('resource')}")
