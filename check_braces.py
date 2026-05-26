with open('templates/coding/chat.html', 'r', encoding='utf-8') as f:
    content = f.read()

start_tag = '<script>'
end_tag = '</script>'

start_idx = content.find(start_tag)
while start_idx != -1:
    end_idx = content.find(end_tag, start_idx)
    if end_idx == -1:
        print("Unclosed <script> tag")
        break
    
    script_content = content[start_idx + len(start_tag):end_idx]
    
    # Check braces
    stack = []
    lines = script_content.split('\n')
    for i, line in enumerate(lines):
        for char in line:
            if char == '{':
                stack.append(('{', i+1))
            elif char == '}':
                if not stack:
                    print(f"Unmatched '}}' at line {i+1}")
                else:
                    stack.pop()
    
    if stack:
        for char, line in stack:
            print(f"Unmatched '{char}' from line {line}")
            
    start_idx = content.find(start_tag, end_idx)
