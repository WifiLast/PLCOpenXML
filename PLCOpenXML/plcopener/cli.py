#!/usr/bin/env python3
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

from . import ProjectExtractor, ProjectInserter
from .xml_utils import NS


def extract_main():
    parser = argparse.ArgumentParser(description="Extract Structured Text from a PLCOpen XML file.")
    parser.add_argument("xml_file", help="Input PLCOpen XML file")
    parser.add_argument("-o", "--output", default="st_output", help="Output directory for ST files")
    parser.add_argument("--flat", action="store_true", help="Don't create subfolders for project structure")
    args = parser.parse_args()

    xml_path = Path(args.xml_file)
    output_dir = Path(args.output)

    extractor = ProjectExtractor(xml_path)
    extractor.extract(output_dir, flat=args.flat)
    print(f"\nDone -> {output_dir.resolve()}")


def insert_main():
    parser = argparse.ArgumentParser(
        description="Insert changed ST code and KBUS mappings back into a PLCOpen XML file."
    )
    parser.add_argument("xml_file", help="Input XML file")
    parser.add_argument(
        "--st-dir",
        default="st_output",
        help="Directory containing extracted .st files. Default: st_output",
    )
    parser.add_argument(
        "--kbus-dir",
        help="Directory containing KBUS .st files. Default: <st-dir>/kbus",
    )
    parser.add_argument(
        "--fieldbus-dir",
        help="Directory containing Fieldbus .st files. Default: <st-dir>/Fieldbus",
    )
    parser.add_argument("-o", "--output", help="Output XML file. Defaults to <input>_updated.xml")
    args = parser.parse_args()

    xml_path = Path(args.xml_file)
    st_dir = Path(args.st_dir)
    kbus_dir = Path(args.kbus_dir) if args.kbus_dir else st_dir / "kbus"
    fieldbus_dir = Path(args.fieldbus_dir) if args.fieldbus_dir else st_dir / "Fieldbus"
    output_path = Path(args.output) if args.output else None

    # Register namespaces for ET
    ET.register_namespace("", NS)
    ET.register_namespace("xhtml", "http://www.w3.org/1999/xhtml")

    inserter = ProjectInserter(xml_path)
    results = inserter.insert(st_dir, kbus_dir, fieldbus_dir, output_path)

    print(f"Wrote {results['output_path']}")
    print(f"Created objects: {results['created_objects']}")
    print(f"Updated POUs: {results['updated_pous']}")
    print(f"Updated data types: {results['updated_data_types']}")
    print(f"Updated configurations: {results['updated_configs']}")
    print(f"Updated bit mappings: {results['updated_bitfields']}")
    print(f"Updated scalar parameters: {results['updated_scalars']}")
    print(f"Updated fieldbus parameters: {results['updated_fieldbus_scalars']}")


if __name__ == "__main__":
    # This module is meant to be used via entry points, 
    # but we can handle direct execution if needed.
    extract_main()
