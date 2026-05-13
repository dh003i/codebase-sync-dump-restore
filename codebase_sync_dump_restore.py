#!/usr/bin/env python3
import os
import sys
import argparse
import hashlib
import ast
import re
from collections import namedtuple

# --- SCHEMA & CONFIGURATION ---
Language_Config = namedtuple('LangConfig', [
    'single_line_comment', 
    'multi_line_comment_open', 
    'multi_line_comment_close', 
    'orgmode_langblock_nm'
])

EXT_SCHEMA = {
    '.py':   Language_Config('#', None, None, 'python'),
    '.sh':   Language_Config('#', None, None, 'bash'),
    '.yaml': Language_Config('#', None, None, 'yaml'),
    '.yml':  Language_Config('#', None, None, 'yaml'),
    '.js':   Language_Config('//', '/*', '*/', 'javascript'),
    '.ts':   Language_Config('//', '/*', '*/', 'typescript'),
    '.c':    Language_Config('//', '/*', '*/', 'c'),
    '.cpp':  Language_Config('//', '/*', '*/', 'cpp'),
    '.h':    Language_Config('//', '/*', '*/', 'cpp'),
    '.html': Language_Config(None, '', '', 'html'),
    '.xml':  Language_Config(None, '', '', 'xml'),
    '.css':  Language_Config(None, '/*', '*/', 'css'),
    '.md':   Language_Config(None, '', '', 'markdown'),
    '.rs':   Language_Config('//', '/*', '*/', 'rust'),
    '.go':   Language_Config('//', '/*', '*/', 'go'),
    '.sql':  Language_Config('--', '/*', '*/', 'sql'),
    '.json': Language_Config(None, None, None, 'json'),
    '.org':  Language_Config(None, None, None, 'org')
}

DEFAULTS = {'delim': '•', 'start_q': '«', 'end_q': '»', 'escape': '\\'}
IGNORE_DIRS = {'.git', '__pycache__', 'node_modules', 'venv', '.venv', '.idea', '.vscode'}
MANDATORY_IGNORE_EXTS = {
    '.pyc', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.pdf', '.mp4', '.mp3', '.wav',
    '.so', '.o', '.bin', '.exe', '.dll', '.zip', '.tar', '.gz', '.7z', '.rar',
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.mdb', '.accdb',
    '.odt', '.ods', '.odp', '.odg', '.odf'
}

# --- CLEANING UTILITIES (CONSOLIDATED) ---

def clean_raw_line(line):
    """General whitespace removal for non-payload lines."""
    return line.strip()

def clean_extension_input(user_input):
    """Sanitizes user-provided extension strings from CLI or prompt."""
    val = clean_raw_line(user_input)
    if not val:
        return set()
    return set(re.split(r'[ ,;]+', val.lower()))

def clean_comment_line(line, marker=None):
    """Strips markers and whitespace for summary extraction only."""
    s_line = clean_raw_line(line)
    if marker and s_line.startswith(marker):
        return clean_raw_line(s_line[len(marker):])
    return s_line.lstrip('*').strip()

def clean_summary_text(raw_text):
    """Refines docstrings into brief (header-safe) and detailed summaries."""
    if not raw_text:
        return "No summary", ""
    cleaned_raw = clean_raw_line(raw_text)
    lines = cleaned_raw.split('\n')
    brief = clean_raw_line(lines[0])
    if len(brief) > 77:
        brief = brief[:77] + "..."
    return brief, cleaned_raw

def clean_metadata_path(line, sq, eq):
    """Extracts and cleans the file path from a metadata line."""
    try:
        start_idx = line.index(sq) + len(sq)
        end_idx = line.index(eq, start_idx)
        return clean_raw_line(line[start_idx:end_idx])
    except ValueError:
        return None

def clean_property_value(line):
    """Extracts a value from an Org-mode property line (:KEY: VALUE)."""
    parts = line.split(':', 2)
    if len(parts) >= 3:
        return clean_raw_line(parts[2])
    return ""

# --- CORE LOGIC ---

def hash_content(content):
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def get_ast_metadata(filepath, content):
    if not filepath.endswith('.py'): return "[]", "[]"
    try:
        tree = ast.parse(content, filename=filepath)
        symbols = [f"{n.name} (func)" for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        depends = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module]
        return f"[{', '.join(set(depends))}]", f"[{', '.join(set(symbols))}]"
    except: return "[Parse Error]", "[Parse Error]"

def get_doc(filepath, content):
    doc = None
    ext = os.path.splitext(filepath)[1].lower()
    if filepath.endswith('.py'):
        try: doc = ast.get_docstring(ast.parse(content))
        except: pass
    if not doc:
        cfg = EXT_SCHEMA.get(ext, Language_Config('#', None, None, ''))
        lines, extracted, in_m = content.splitlines(), [], False
        for l in lines:
            s_l = clean_raw_line(l)
            if not s_l or (not extracted and s_l.startswith('#!')): continue
            if in_m:
                if cfg.multi_line_comment_close and cfg.multi_line_comment_close in l: 
                    extracted.append(clean_comment_line(l.split(cfg.multi_line_comment_close)[0]))
                    break
                extracted.append(clean_comment_line(l))
            elif cfg.multi_line_comment_open and s_l.startswith(cfg.multi_line_comment_open):
                in_m = True
                content_after = s_l[len(cfg.multi_line_comment_open):].split(cfg.multi_line_comment_close)[0]
                if clean_raw_line(content_after): extracted.append(clean_raw_line(content_after))
                if cfg.multi_line_comment_close and cfg.multi_line_comment_close in l: break
            elif cfg.single_line_comment and s_l.startswith(cfg.single_line_comment):
                extracted.append(clean_comment_line(l, cfg.single_line_comment))
            else: break
        doc = "\n".join(extracted)
    return clean_summary_text(doc)

def scan_extensions(in_dir, out_file):
    found = set()
    out_base = os.path.basename(out_file)
    for r, d, fs in os.walk(in_dir):
        d[:] = [di for di in d if di not in IGNORE_DIRS]
        for f in fs:
            ext = os.path.splitext(f)[1].lower()
            if ext and ext not in MANDATORY_IGNORE_EXTS and f != out_base:
                found.add(ext.lstrip('.'))
    return sorted(list(found))

def run_dump(in_dir, out_file, cfg, extra_ignore=None):
    extra_ignore = extra_ignore or set()
    out_name = os.path.basename(out_file)
    proj = os.path.basename(os.path.abspath(in_dir))
    with open(out_file, 'w', encoding='utf-8') as out:
        out.write(f"* PROJECT: {proj} :summary:codedump:v9_2:\n:PROPERTIES:\n:CD_VERSION: 9.2\n")
        out.write(f":CD_PREFIX: ** _FileSumm_: \n:CD_START_Q: {cfg['start_q']}\n:CD_END_Q: {cfg['end_q']}\n")
        out.write(f":CD_DELIM: {cfg['delim']} \n:CD_ESCAPE: {cfg['escape']}\n:END:\n\n")
        for r, d, fs in os.walk(in_dir):
            d[:] = [di for di in d if di not in IGNORE_DIRS]
            for f in fs:
                ext = os.path.splitext(f)[1].lower()
                if ext in MANDATORY_IGNORE_EXTS or ext.lstrip('.') in extra_ignore or f == out_name: continue
                path = os.path.join(r, f)
                rel = os.path.relpath(path, in_dir)
                try: content = open(path, 'r', encoding='utf-8').read()
                except: continue
                dep, sym = get_ast_metadata(path, content)
                brief, full = get_doc(path, content)
                h, sq, eq, dl = hash_content(content), cfg['start_q'], cfg['end_q'], cfg['delim']
                out.write(f"** _FileSumm_: {sq}{rel}{eq} {dl} {sq}{brief}{eq} {dl} :file:\n")
                out.write(f":PROPERTIES:\n:DEPENDS_ON: {dep}\n:SYMBOLS: {sym}\n:SHA256: {h}\n:END:\n")
                if full and full != brief: out.write(f"_Description_:\n{full}\n\n")
                l_cfg = EXT_SCHEMA.get(ext, Language_Config(None,None,None,''))
                out.write(f"#+BEGIN_SRC {l_cfg.orgmode_langblock_nm}\n")
                
                for line in content.splitlines(keepends=True):
                    out.write(f"  {line}") # 2-space protocol padding
                
                # VISUAL ENCODING (V9.4): Unconditional newline injection.
                # Creates a visual blank line for standard files, and cleanly wraps 
                # non-terminated files, deterministically encoding the EOF state.
                out.write(f"\n#+END_SRC\n\n")
    print(f"Dump complete: {out_file}")

def run_restore(in_file, out_dir):
    if not os.path.exists(in_file): sys.exit(f"Error: {in_file} not found.")
    lines = open(in_file, 'r', encoding='utf-8').readlines()
    
    # Isolate properties explicitly to avoid trailing invisible characters
    props = {}
    for l in lines:
        if l.startswith(':CD_'):
            parts = l.split(':', 2)
            if len(parts) >= 3:
                props[parts[1].strip()] = clean_raw_line(parts[2])
                
    sq, eq = props.get('CD_START_Q', '«'), props.get('CD_END_Q', '»')
    pref = props.get('CD_PREFIX', '** _FileSumm_:')
    
    curr, h_exp, in_s, buf = None, None, False, []
    restored_count = 0
    diag_files_found = 0
    
    for l in lines:
        # Match prefix securely (ignoring trailing whitespace on the line)
        if clean_raw_line(l).startswith(pref):
            curr = clean_metadata_path(l, sq, eq)
            if curr: diag_files_found += 1
            continue
            
        if curr and clean_raw_line(l).startswith(":SHA256:"): 
            h_exp = clean_property_value(l)
            continue
            
        # Strict Column-0 check that ignores trailing newline differences
        if curr and l.startswith("#+BEGIN_SRC"): 
            in_s, buf = True, []
            continue
            
        if in_s:
            if l.startswith("#+END_SRC"): 
                in_s = False
                out_p = os.path.join(out_dir, curr)
                os.makedirs(os.path.dirname(out_p), exist_ok=True)
                
                body = "".join(buf)
                
                # DETERMINISTIC RESTORE (V9.4):
                # Because the dump unconditionally injected \n#+END_SRC, we simply 
                # strip exactly one \n to guarantee bit-for-bit parity for both file types.
                if body.endswith('\n'): 
                    body = body[:-1] 
                
                if h_exp and hash_content(body) != h_exp: 
                    print(f"FAILED: Hash mismatch on {curr}")
                else: 
                    with open(out_p, 'w', encoding='utf-8') as f:
                        f.write(body)
                    print(f"Restored: {curr}")
                    restored_count += 1
                curr, buf = None, []
            else:
                buf.append(l[2:] if l.startswith("  ") else l) # Remove 2-space padding

    # Diagnostic Engine
    if restored_count == 0:
        print("\n--- RESTORE FAILURE DIAGNOSTICS ---")
        print(f"Target Input File: {in_file}")
        print(f"Extracted CD_PREFIX: '{pref}'")
        print(f"Files detected via prefix: {diag_files_found}")
        if diag_files_found == 0:
            print("Reason: State Machine never started. The prefix in the file does not match the parsed CD_PREFIX.")
        else:
            print("Reason: State Machine stalled. Files were detected, but #+BEGIN_SRC or #+END_SRC were missing at Column 0.")

def main():
    parser = argparse.ArgumentParser(description="Codebase Sync V9.2")
    sub = parser.add_subparsers(dest="command")
    d_p = sub.add_parser("dump")
    d_p.add_argument("-d", "--dir", default=".")
    d_p.add_argument("-o", "--out", default="dump.org")
    d_p.add_argument("-x", "--exclude", help="Comma separated extensions to exclude")
    r_p = sub.add_parser("restore")
    r_p.add_argument("-i", "--in-file", default="dump.org")
    r_p.add_argument("-o", "--out-dir", default="./restored_repo")
    args = parser.parse_args()
    if not args.command:
        raw_cmd = clean_raw_line(input("Mode: [d]ump or [r]estore: ")).lower()
        if raw_cmd == 'd':
            in_d = clean_raw_line(input("Target dir [.]: ")) or "."
            out_f = clean_raw_line(input("Output file [dump.org]: ")) or "dump.org"
            exts = scan_extensions(in_d, out_f)
            print(f"\nPotential extensions: {' '.join(exts)}")
            extra = clean_extension_input(input("IGNORE extensions (space/comma/semicolon sep): "))
            run_dump(in_d, out_f, DEFAULTS, extra)
        elif raw_cmd == 'r':
            in_f = clean_raw_line(input("Input file [dump.org]: ")) or "dump.org"
            out_d = clean_raw_line(input("Output dir [./restored_repo]: ")) or "./restored_repo"
            run_restore(in_f, out_d)
    elif args.command == "dump":
        run_dump(args.dir, args.out, DEFAULTS, clean_extension_input(args.exclude))
    elif args.command == "restore":
        run_restore(args.in_file, args.out_dir)

if __name__ == "__main__":
    main()
