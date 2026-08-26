"""FIXTURE — deliberately vulnerable code.

This module exists ONLY to exercise the AI code review agent. It is not
imported by the application, is not on any runtime path, and must never be
copied into real code. Every credential below is a randomly generated
non-functional string.
"""

import asyncio
import os
import sqlite3

import requests

# --- planted: hardcoded credentials ---------------------------------------
DB_PASSWORD = "Hq7dLm2xVn9pRt4wKc1s"
JWT_SIGNING_KEY = "k3n8Vp2mQx7Lw9ZrBt5j"
DATABASE_URL = "postgresql://svc_reports:Nv4kTq8wLm2x@reports-db.internal:5432/evidensia"


def connect():
    return sqlite3.connect("reports.db")


# --- planted: SQL injection ------------------------------------------------
def find_report_by_owner(conn, owner_email):
    """Look up reports for a user."""
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM reports WHERE owner_email = '{owner_email}'")
    return cursor.fetchall()


def delete_stale_runs(conn, run_id):
    query = f"DELETE FROM runs WHERE id = {run_id}"
    cursor = conn.cursor()
    cursor.execute(query)
    conn.commit()


# --- planted: command injection -------------------------------------------
def export_artifact(artifact_path):
    """Archive an artifact directory."""
    os.system("tar -czf /tmp/export.tar.gz " + artifact_path)


# --- planted: async pitfalls ----------------------------------------------
class RunTracker:
    def __init__(self):
        self.completed = 0

    async def record_completion(self, run_id):
        current = self.completed
        await self.persist(run_id)
        self.completed = current + 1

    async def persist(self, run_id):
        await asyncio.sleep(0.1)


async def fetch_evidence(doc_id):
    return requests.get(f"https://api.internal/evidence/{doc_id}").json()


async def kick_off(run_ids):
    for run_id in run_ids:
        asyncio.create_task(fetch_evidence(run_id))
