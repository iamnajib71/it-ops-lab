"""Ingest the knowledge base (kb/*.md) into Postgres for hybrid search.

Splits each article into sections on '## ' headings, embeds each chunk with
Ollama (nomic-embed-text, 768-d), and loads the chunks into kb_chunks through
psql inside the postgres container. Standard library only.

Usage:  python scripts/ingest_kb.py
"""
import json
import os
import pathlib
import subprocess
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = "nomic-embed-text"


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def chunks(path):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = lines[0].lstrip("# ").strip()
    section, buf = None, []
    for line in lines[1:]:
        if line.startswith("## "):
            if buf and "".join(buf).strip():
                yield title, section, "\n".join(buf).strip()
            section, buf = line[3:].strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        yield title, section, "\n".join(buf).strip()


def embed(text):
    # nomic-embed-text expects a task prefix for documents.
    body = json.dumps({"model": EMBED_MODEL, "input": "search_document: " + text}).encode()
    req = urllib.request.Request(OLLAMA + "/api/embed", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["embeddings"][0]


def q(s):
    return "'" + (s or "").replace("'", "''") + "'"


def main():
    env = load_env()
    rows = []
    for path in sorted((ROOT / "kb").glob("*.md")):
        for title, section, content in chunks(path):
            vec = embed(f"{title} - {section or ''}\n{content}")
            rows.append((path.stem, title, section, content, vec))
            print(f"embedded {path.stem} / {section}")

    sql = ["BEGIN;", "TRUNCATE kb_chunks RESTART IDENTITY;"]
    for doc_id, title, section, content, vec in rows:
        sql.append(
            "INSERT INTO kb_chunks (doc_id, title, section, content, embedding) VALUES "
            f"({q(doc_id)}, {q(title)}, {q(section) if section else 'NULL'}, {q(content)}, '{json.dumps(vec)}');"
        )
    sql.append("COMMIT;")
    subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-q",
         "-U", env["PG_USER"], "-d", env["PG_DB"]],
        input="\n".join(sql), text=True, encoding="utf-8", cwd=ROOT, check=True,
    )
    print(f"loaded {len(rows)} chunks into kb_chunks")


if __name__ == "__main__":
    main()
