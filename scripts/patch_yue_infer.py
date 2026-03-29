"""Patch YuE's infer.py to accept --temperature and --top_p as CLI args."""
import sys

path = "/yue/inference/infer.py"
with open(path) as f:
    code = f.read()

# Add argparse entries after --repetition_penalty line
lines = code.split("\n")
new_lines = []
for line in lines:
    new_lines.append(line)
    if "--repetition_penalty" in line and "add_argument" in line:
        indent = len(line) - len(line.lstrip())
        sp = " " * indent
        new_lines.append(sp + 'parser.add_argument("--temperature", type=float, default=1.0, help="Sampling temperature")')
        new_lines.append(sp + 'parser.add_argument("--top_p", type=float, default=0.93, help="Top-p sampling")')
code = "\n".join(new_lines)

# Replace hardcoded values with args references
code = code.replace("temperature=1.0", "temperature=args.temperature")
code = code.replace("top_p=0.93", "top_p=args.top_p")

# Fix "File name too long" error: YuE uses full genre text in output filenames.
# The variable is called `genres` — truncate it right after it's loaded from file,
# but ONLY for filename construction. We do this by truncating the genres var itself
# since infer.py only uses it for filenames (the model gets genre via the tokenized prompt).
import re
# Match: genres = open(...).read().strip() or similar
code = re.sub(
    r'(genres\s*=\s*[^\n]*\.read\(\)[^\n]*)',
    r'\1\ngenres = genres[:60]  # Truncate to avoid ENAMETOOLONG in output filenames',
    code,
    count=1,
)

with open(path, "w") as f:
    f.write(code)
print("Patched infer.py: added --temperature, --top_p args + filename truncation")
