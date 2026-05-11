from setuptools import setup, find_packages

setup(
    name="plcopener",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[],
    entry_points={
        "console_scripts": [
            "plcopen-extract=plcopener.cli:extract_main",
            "plcopen-insert=plcopener.cli:insert_main",
        ],
    },
    author="Martin St.",
    description="Tools for extracting and inserting Structured Text in PLCOpen XML files",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    license="Other/Proprietary",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
)
