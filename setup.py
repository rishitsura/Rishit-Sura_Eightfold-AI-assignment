from setuptools import setup, find_packages

setup(
    name="eightfold-transformer",
    version="1.0.0",
    description="Multi-Source Candidate Data Transformer",
    author="Rishi Sharma",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.11",
    install_requires=[
        "pydantic>=2.0,<3.0",
        "phonenumbers>=8.13",
        "pycountry>=23.12",
        "python-docx>=1.0",
        "pdfplumber>=0.10",
        "requests>=2.31",
        "rapidfuzz>=3.5",
        "dateparser>=1.2",
        "click>=8.1",
    ],
    entry_points={
        "console_scripts": [
            "eightfold-transform=transformer.cli:main",
        ],
    },
)
