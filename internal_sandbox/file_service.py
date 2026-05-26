"""
FileService — Operações de filesystem internas (sem AIO Sandbox).
Usa Python nativo: pathlib, os, re, fnmatch.
"""
from __future__ import annotations

import base64
import fnmatch
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class FileService:
    """Operações de arquivo usando Python puro."""

    DEFAULT_ROOT: str = os.environ.get(
        "INTERNAL_SANDBOX_ROOT",
        os.path.join(os.path.expanduser("~"), "fluxi_sandbox"),
    )

    @classmethod
    def _resolve(cls, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return Path(cls.DEFAULT_ROOT) / path

    # ── Leitura ──────────────────────────────────────────────────

    @classmethod
    def read_file(
        cls,
        file: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        sudo: bool = False,
    ) -> Dict[str, Any]:
        p = cls._resolve(file)
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            if start_line is not None or end_line is not None:
                lines = content.splitlines(keepends=True)
                sl = start_line or 0
                el = end_line if end_line is not None else len(lines)
                content = "".join(lines[sl:el])
            return {"content": content}
        except FileNotFoundError:
            return {"error": f"Arquivo não encontrado: {file}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Escrita ──────────────────────────────────────────────────

    @classmethod
    def write_file(
        cls,
        file: str,
        content: str,
        append: bool = False,
        encoding: Optional[str] = None,
        leading_newline: bool = False,
        trailing_newline: bool = False,
        sudo: bool = False,
    ) -> Dict[str, Any]:
        p = cls._resolve(file)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            if encoding == "base64":
                data = base64.b64decode(content)
                mode = "ab" if append else "wb"
                with open(p, mode) as f:
                    f.write(data)
            else:
                text = content
                if leading_newline:
                    text = "\n" + text
                if trailing_newline:
                    text = text + "\n"
                mode = "a" if append else "w"
                with open(p, mode, encoding="utf-8") as f:
                    f.write(text)
            return {"success": True, "message": f"Arquivo {file} escrito com sucesso"}
        except Exception as e:
            return {"error": str(e)}

    # ── Listagem ─────────────────────────────────────────────────

    @classmethod
    def list_path(
        cls,
        path: str,
        recursive: bool = False,
        show_hidden: bool = False,
    ) -> Dict[str, Any]:
        p = cls._resolve(path)
        try:
            files: List[Dict[str, Any]] = []
            iterator = p.rglob("*") if recursive else p.iterdir()
            for item in iterator:
                if not show_hidden and item.name.startswith("."):
                    continue
                try:
                    stat = item.stat()
                    name = str(item.relative_to(p)) if recursive else item.name
                    files.append({
                        "name": name,
                        "type": "directory" if item.is_dir() else "file",
                        "size": stat.st_size if item.is_file() else None,
                    })
                except Exception:
                    pass
            files.sort(key=lambda x: (x["type"] != "directory", x["name"].lower()))
            return {"files": files}
        except FileNotFoundError:
            return {"error": f"Diretório não encontrado: {path}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Busca ────────────────────────────────────────────────────

    @classmethod
    def find_files(cls, path: str, glob: str) -> Dict[str, Any]:
        p = cls._resolve(path)
        try:
            found = [
                str(f)
                for f in p.rglob(glob)
                if not any(part.startswith(".") for part in f.parts[-5:])
            ]
            return {"files": sorted(found)}
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def grep_files(
        cls,
        path: str,
        pattern: str,
        include: Optional[List[str]] = None,
        case_insensitive: bool = True,
        max_results: int = 50,
    ) -> Dict[str, Any]:
        p = cls._resolve(path)
        flags = re.IGNORECASE if case_insensitive else 0
        matches: List[str] = []
        try:
            compiled = re.compile(pattern, flags)
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for fname in files:
                    if fname.startswith("."):
                        continue
                    if include and not any(fnmatch.fnmatch(fname, pat) for pat in include):
                        continue
                    fpath = Path(root) / fname
                    try:
                        text = fpath.read_text(encoding="utf-8", errors="replace")
                        for i, line in enumerate(text.splitlines(), 1):
                            if compiled.search(line):
                                matches.append(f"{fpath}:{i}: {line.rstrip()}")
                                if len(matches) >= max_results:
                                    return {"matches": matches, "truncated": True}
                    except Exception:
                        pass
            return {"matches": matches}
        except re.error as e:
            return {"error": f"Regex inválida: {e}"}
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def search_in_file(
        cls, file: str, regex: str, sudo: bool = False
    ) -> Dict[str, Any]:
        p = cls._resolve(file)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            compiled = re.compile(regex)
            matches = []
            for i, line in enumerate(text.splitlines(), 1):
                m = compiled.search(line)
                if m:
                    matches.append({
                        "line_number": i,
                        "line": line,
                        "match": m.group(0),
                    })
            return {"matches": matches}
        except re.error as e:
            return {"error": f"Regex inválida: {e}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Edição ───────────────────────────────────────────────────

    @classmethod
    def replace_in_file(
        cls, file: str, old_str: str, new_str: str, sudo: bool = False
    ) -> Dict[str, Any]:
        p = cls._resolve(file)
        try:
            content = p.read_text(encoding="utf-8")
            if old_str not in content:
                return {"error": f"String não encontrada no arquivo: {old_str[:80]}"}
            p.write_text(content.replace(old_str, new_str, 1), encoding="utf-8")
            return {"success": True, "message": "Substituição realizada"}
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def str_replace_editor(
        cls,
        command: str,
        path: str,
        file_text: Optional[str] = None,
        old_str: Optional[str] = None,
        new_str: Optional[str] = None,
        insert_line: Optional[int] = None,
        view_range: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        p = cls._resolve(path)

        if command == "view":
            try:
                if p.is_dir():
                    items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
                    listing = "\n".join(
                        f"{'[D]' if i.is_dir() else '[F]'} {i.name}"
                        for i in items
                        if not i.name.startswith(".")
                    )
                    return {"output": f"Diretório {path}:\n{listing}"}
                content = p.read_text(encoding="utf-8", errors="replace")
                lines = content.splitlines()
                if view_range and len(view_range) == 2:
                    sl, el = view_range[0] - 1, view_range[1]
                    lines = lines[sl:el]
                    numbered = "\n".join(f"{sl+i+1:4d} │ {line}" for i, line in enumerate(lines))
                else:
                    numbered = "\n".join(f"{i+1:4d} │ {line}" for i, line in enumerate(lines))
                return {"output": numbered}
            except Exception as e:
                return {"error": str(e)}

        elif command == "create":
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(file_text or "", encoding="utf-8")
                return {"output": f"Arquivo {path} criado com sucesso"}
            except Exception as e:
                return {"error": str(e)}

        elif command == "str_replace":
            if old_str is None:
                return {"error": "old_str é obrigatório para str_replace"}
            return cls.replace_in_file(path, old_str, new_str or "")

        elif command == "insert":
            if insert_line is None or new_str is None:
                return {"error": "insert_line e new_str são obrigatórios para insert"}
            try:
                content = p.read_text(encoding="utf-8")
                lines = content.splitlines(keepends=True)
                lines.insert(insert_line, new_str + "\n")
                p.write_text("".join(lines), encoding="utf-8")
                return {"output": f"Inserido após linha {insert_line}"}
            except Exception as e:
                return {"error": str(e)}

        elif command == "undo_edit":
            return {"output": "undo_edit não suportado no sandbox interno"}

        return {"error": f"Comando '{command}' não reconhecido"}

    # ── Download / Upload ────────────────────────────────────────

    @classmethod
    def download_file_bytes(cls, path: str) -> bytes:
        return cls._resolve(path).read_bytes()

    @classmethod
    def upload_file(
        cls, path: str, filename: str, content_base64: str
    ) -> Dict[str, Any]:
        p = cls._resolve(path)
        p.mkdir(parents=True, exist_ok=True)
        fpath = p / filename
        fpath.write_bytes(base64.b64decode(content_base64))
        return {"success": True, "path": str(fpath)}

    # ── Edição cirúrgica (EditTool estilo Claude Code) ────────────

    @classmethod
    def edit_file(
        cls,
        file: str,
        old_str: str,
        new_str: str,
        expected_replacements: int = 1,
    ) -> Dict[str, Any]:
        """
        Substitui exatamente `expected_replacements` ocorrências de old_str por new_str.
        Equivalente ao EditTool do Claude Code: preciso, verifica unicidade.
        """
        p = cls._resolve(file)
        try:
            content = p.read_text(encoding="utf-8")
            count = content.count(old_str)
            if count == 0:
                # Tenta fornecer contexto para debugging
                snippet = old_str[:120].replace("\n", "↵")
                return {
                    "error": (
                        f"String não encontrada no arquivo '{file}'. "
                        f"Verifique espaços, indentação e quebras de linha. "
                        f"Trecho buscado: {snippet!r}"
                    )
                }
            if count != expected_replacements:
                return {
                    "error": (
                        f"Encontradas {count} ocorrência(s), mas expected_replacements={expected_replacements}. "
                        f"Forneça mais contexto em old_str para identificar unicamente o trecho, "
                        f"ou ajuste expected_replacements."
                    )
                }
            new_content = content.replace(old_str, new_str, expected_replacements)
            p.write_text(new_content, encoding="utf-8")
            return {
                "success": True,
                "replacements": expected_replacements,
                "message": f"Substituição realizada em '{file}' ({expected_replacements}x)",
            }
        except FileNotFoundError:
            return {"error": f"Arquivo não encontrado: {file}"}
        except Exception as e:
            return {"error": str(e)}

    # ── ZIP ──────────────────────────────────────────────────────

    @classmethod
    def zip_path(
        cls,
        source_path: str,
        output_path: Optional[str] = None,
        include_hidden: bool = False,
    ) -> Dict[str, Any]:
        """
        Cria um arquivo .zip de source_path (arquivo ou diretório).
        Se output_path não informado, cria {source_path}.zip.
        Retorna o caminho absoluto do zip criado.
        """
        import zipfile
        import time

        p = cls._resolve(source_path)
        if not p.exists():
            return {"error": f"Caminho não encontrado: {source_path}"}

        if output_path:
            out = cls._resolve(output_path)
        else:
            out = p.parent / (p.name + ".zip")

        out.parent.mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
                if p.is_file():
                    zf.write(p, p.name)
                    files_count = 1
                else:
                    files_count = 0
                    for item in p.rglob("*"):
                        # Ignora ocultos se não incluídos
                        if not include_hidden and any(
                            part.startswith(".") for part in item.relative_to(p).parts
                        ):
                            continue
                        if item.is_file():
                            arcname = item.relative_to(p.parent)
                            zf.write(item, arcname)
                            files_count += 1

            size_kb = round(out.stat().st_size / 1024, 1)
            return {
                "success": True,
                "zip_path": str(out),
                "files_count": files_count,
                "size_kb": size_kb,
                "message": f"ZIP criado: {out} ({files_count} arquivo(s), {size_kb} KB)",
            }
        except Exception as e:
            return {"error": str(e)}

    # ── Workspace info (para o coding agent) ─────────────────────

    @classmethod
    def workspace_info(cls, workspace_path: str) -> Dict[str, Any]:
        """
        Retorna informações rápidas do workspace: estrutura de arquivos,
        git status (se for repo), arquivos modificados recentemente.
        """
        import subprocess
        import time

        p = cls._resolve(workspace_path)
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)

        # Listagem de 1 nível
        items = []
        try:
            for item in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name)):
                if item.name.startswith("."):
                    continue
                items.append(f"{'/' if item.is_dir() else ' '} {item.name}")
        except Exception:
            pass

        info: Dict[str, Any] = {
            "workspace": str(p),
            "contents": items[:50],
        }

        # Git status (se disponível)
        try:
            result = subprocess.run(
                ["git", "status", "--short"],
                cwd=str(p),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                info["git_status"] = result.stdout.strip() or "clean"
                branch_result = subprocess.run(
                    ["git", "branch", "--show-current"],
                    cwd=str(p),
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                info["git_branch"] = branch_result.stdout.strip()
        except Exception:
            info["git_status"] = "not a git repo"

        return info
