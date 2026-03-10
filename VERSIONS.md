# System Version Documentation
*Generated on March 10, 2026*

## Release Notes

### Hotfix / E2E Update
- Handled a bug in `indexer.py` where Kiwix serve default mount generation was disjointed against `offline-search` URL generation. Swapped indexing parser from `library.xml`'s `name` to the underlying SQLite physical `zim.stem`. 
- Overhauled testing methodology. Removed pure mocks and replaced them with robust full E2E pipeline and functional HTTP testing tests (`test_e2e_journey.py`, `test_build_library_integration.py`).

This document lists the exact versions of all tools and libraries used to validate and run the Offline Search system. Use these versions to ensure maximum compatibility in air-gapped environments.

## 1. Core Tools

| Tool | Version | Notes |
|------|---------|-------|
| **Python** | 3.14.0 | Tested with 3.14.0. Codebase is compatible with 3.11+. |
| **Kiwix Tools** | 3.7.0 | Build: `kiwix-tools_win-i686-3.7.0-2`<br>Includes: `libkiwix 13.1.0`, `libzim 9.2.1` |
| **Operating System** | Windows | Tested on Windows 10/11 Architecture |

## 2. Python Dependencies (Frozen)

The following exact versions were installed and tested in the virtual environment:

```text
annotated-types==0.7.0
anyio==4.12.1
attrs==25.4.0
beautifulsoup4==4.14.3
certifi==2026.1.4
cffi==2.0.0
charset-normalizer==3.4.4
click==8.3.1
colorama==0.4.6
cryptography==46.0.4
falcon==4.2.0
gevent==25.9.1
greenlet==3.3.1
h11==0.16.0
httpcore==1.0.9
httpx==0.28.1
httpx-sse==0.4.3
idna==3.11
jsonschema==4.26.0
jsonschema-specifications==2025.9.1
Mako==1.3.10
MarkupSafe==3.0.3
mcp==1.26.0
pycparser==3.0
pydantic==2.12.5
pydantic-settings==2.12.0
pydantic_core==2.41.5
PyJWT==2.11.0
python-dotenv==1.2.1
python-multipart==0.0.22
pywin32==311
referencing==0.37.0
requests==2.32.5
rpds-py==0.30.0
setuptools==80.10.2
soupsieve==2.8.3
sse-starlette==3.2.0
starlette==0.52.1
typing-inspection==0.4.2
typing_extensions==4.15.0
urllib3==2.6.3
uvicorn==0.40.0
zimply==1.1.4
zope.event==6.1
zope.interface==8.2
zstandard==0.25.0
```

## 3. Deployment Notes

- **Kiwix Compatibility**: Use the included `kiwix-serve.exe` (v3.7.0) found in the `dist` folder. Newer versions of Kiwix (e.g., v3.8+) may have different command-line arguments.
- **Python Compatibility**: If Python 3.14 is not available on the target machine, Python 3.11, 3.12, or 3.13 are verified alternatives.
- **Wheel Files**: If the target machine cannot install from PyPI, you must download the `.whl` files for the packages listed above corresponding to the target OS and Python version.

