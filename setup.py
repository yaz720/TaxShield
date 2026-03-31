from setuptools import setup, find_packages

setup(
    name="taxshield",
    version="0.1.0",
    description="Tax document PII redaction tool",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "PyMuPDF>=1.24.0",
        "click>=8.0",
    ],
    entry_points={
        "console_scripts": [
            "taxshield=taxshield.cli:main",
        ],
    },
)
