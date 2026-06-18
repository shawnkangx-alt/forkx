from setuptools import setup, find_packages
setup(
    name="forkx",
    version="0.1.0",
    packages=find_packages("forkx"),
    package_dir={"forkx": "forkx"},
    install_requires=[],
    entry_points={
        "console_scripts": [
            "forlsx=forkx.code.main:main",
        ],
    },
    python_requires=">=3.8",
)
