#!/usr/bin/env python3
"""
Example usage of the plcopen package for extracting and inserting ST code.
"""

from pathlib import Path
from plcopen import ProjectExtractor, ProjectInserter

def main():
    # 1. Setup paths
    input_xml = Path("test.xml")
    if not input_xml.exists():
        print(f"Error: {input_xml} not found. Please run this in the repository root.")
        return

    st_output_dir = Path("example_st_output")
    updated_xml = Path("test_updated.xml")

    # 2. Extract ST code
    print(f"Extracting {input_xml} to {st_output_dir}...")
    extractor = ProjectExtractor(input_xml)
    extractor.extract(st_output_dir, flat=False)
    print("Extraction complete.\n")

    # 3. Modify a file (Programmatically)
    target_st = st_output_dir / "PLC_PRG.st"
    if target_st.exists():
        print(f"Modifying {target_st}...")
        content = target_st.read_text(encoding="utf-8")
        
        # Add a dummy variable to the VAR block
        if "END_VAR" in content:
            new_content = content.replace("END_VAR", "	programmatic_test : BOOL; (* Added via example script *)\nEND_VAR", 1)
            target_st.write_text(new_content, encoding="utf-8")
            print("Modification applied.")

    # 4. Insert changes back into XML
    print(f"\nInserting changes back into {updated_xml}...")
    inserter = ProjectInserter(input_xml)
    results = inserter.insert(st_output_dir, output_path=updated_xml)

    print("\nResults:")
    print(f"  Updated POUs: {results['updated_pous']}")
    print(f"  Updated Data Types: {results['updated_data_types']}")
    print(f"  Output File: {results['output_path']}")

if __name__ == "__main__":
    main()
