import re

def update_ver(file, search_str, rep_str):
    with open(file, 'r', encoding='utf-8') as f:
        data = f.read()
    data = data.replace(search_str, rep_str)
    with open(file, 'w', encoding='utf-8') as f:
        f.write(data)

update_ver('pyproject.toml', 'version = "1.6.4"', 'version = "1.6.5"')
update_ver('crates/dotscope-core/Cargo.toml', 'version = "1.6.4"', 'version = "1.6.5"')
update_ver('dotscope/__init__.py', '__version__ = "1.6.4"', '__version__ = "1.6.5"')
