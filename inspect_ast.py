import ast

with open("test.py", "r", encoding="utf-8") as f:
    tree = ast.parse(f.read(), filename="test.py")

for node in tree.body:
    if isinstance(node, ast.ClassDef):
        print(f"\nClass: {node.name} (lines {node.lineno} - {node.end_lineno})")
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                print(f"  - Method: {item.name} (line {item.lineno})")
    elif isinstance(node, ast.FunctionDef):
        print(f"Function: {node.name} (line {node.lineno})")
