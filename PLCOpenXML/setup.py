from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="plcopener",
    version="0.1.0",
    author="Martin St.",
    description="Tools for extracting and inserting Structured Text in PLCOpen XML files",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    install_requires=[],
    entry_points={
        "console_scripts": [
            "plcopen-extract=plcopener.cli:extract_main",
            "plcopen-insert=plcopener.cli:insert_main",
        ],
    },
    license="Other/Proprietary",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
        "License :: Other/Proprietary License",
    ],
    python_requires=">=3.7",
    include_package_data=True,
    zip_safe=False,
)
