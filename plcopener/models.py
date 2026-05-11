from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class StVariable:
    name: str
    address: str
    type_name: str
    comment: str

@dataclass
class PouVariable:
    name: str
    type_text: str
    initial_value: Optional[str] = None
    documentation: Optional[str] = None

@dataclass
class PouSection:
    kind: str
    variables: List[PouVariable]
    retain: bool = False
    persistent: bool = False
    constant: bool = False

@dataclass
class PouUpdate:
    name: str
    pou_type: str
    return_type: Optional[str]
    sections: List[PouSection]
    body: str
    extends: Optional[str] = None
    implements: Optional[List[str]] = None

@dataclass
class EnumValue:
    name: str
    value: Optional[str] = None

@dataclass
class DataTypeUpdate:
    name: str
    fields: List[PouVariable] = field(default_factory=list)
    enum_values: List[EnumValue] = field(default_factory=list)
    kind: str = "struct"
