"""Shared test fixtures for the offline-search test suite."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """Create a small in-memory-like FTS5 database for testing."""
    db_path = tmp_path / "test_index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(
        "CREATE VIRTUAL TABLE documents USING fts5("
        "title, content, zim_name, namespace, url, "
        "tokenize='porter'"
        ")"
    )
    conn.execute(
        "CREATE TABLE metadata (docid INTEGER PRIMARY KEY, zim_path TEXT NOT NULL)"
    )

    # Seed with representative test data
    rows = [
        ("Python Tutorial", "Learn Python programming from scratch. Variables, loops, functions.",
         "python_docs", "A", "Python/Tutorial"),
        ("Python asyncio", "The asyncio module provides infrastructure for writing single-threaded concurrent code using coroutines.",
         "python_docs", "A", "library/asyncio.html"),
        ("JavaScript Guide", "JavaScript is a lightweight, interpreted programming language.",
         "devdocs", "A", "javascript/Guide"),
        ("SQLite FTS5 Extension", "FTS5 is a full-text search extension for SQLite. It supports BM25 ranking.",
         "stackoverflow", "A", "sqlite/fts5.html"),
        ("React useEffect Hook", "useEffect lets you synchronize a component with an external system.",
         "devdocs", "A", "react/hooks-effect"),
        ("Python analytics.python.org tracking", "This page should be filtered out due to URL blacklist.",
         "python_docs", "A", "analytics.python.org/track"),
        ("Tutoriel Python (français)", "Apprenez Python en français. Variables, boucles, fonctions.",
         "python_docs", "A", "/fr/Python/Tutorial"),
        ("Go Concurrency Patterns", "Goroutines and channels for concurrent programming in Go.",
         "devdocs", "A", "go/concurrency"),
        ("Database Indexing", "Database indexing improves query performance using B-tree and hash indexes.",
         "stackoverflow", "A", "database/indexing"),
        ("Authentication with OAuth2", "OAuth2 authentication flow for securing REST APIs.",
         "devdocs", "A", "security/oauth2"),
    ]

    for title, content, zim, ns, url in rows:
        cur = conn.execute(
            "INSERT INTO documents (title, content, zim_name, namespace, url) VALUES (?, ?, ?, ?, ?)",
            (title, content, zim, ns, url),
        )
        conn.execute(
            "INSERT INTO metadata (docid, zim_path) VALUES (?, ?)",
            (cur.lastrowid, "/fake/test.zim"),
        )

    conn.commit()
    conn.close()
    return db_path
