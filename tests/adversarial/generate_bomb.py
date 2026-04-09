import os

def create_minified_bomb(path="tests/adversarial/bomb.js", depth=500000):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    # Creates an exponentially deepening anonymous function stack bounded to exactly 1 continuous line
    # to explode Tree-Sitter's recursive descent parser stack pointer limit
    content = "const root = "
    
    # Go deep
    for i in range(depth):
        content += "() => {"
        
    content += "return 42;"
    
    # Climb out
    for i in range(depth):
        content += "}"
        
    content += ";"
    
    with open(path, "w") as f:
        f.write(content)

    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"Generated Payload: {path} ({size_mb:.2f} MB)")

if __name__ == "__main__":
    create_minified_bomb()
