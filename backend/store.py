import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class ConflictError(Exception):
    pass


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.files_dir = self.root / "files"
        self.temp_dir = self.root / "tmp"
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "reports.sqlite3"
        with self.connect() as con:
            con.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, date TEXT NOT NULL,
                size INTEGER NOT NULL, media_type TEXT NOT NULL, sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL, analysis TEXT, analysis_model TEXT
            );
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, date TEXT NOT NULL,
                period_start TEXT NOT NULL, period_end TEXT NOT NULL,
                content TEXT NOT NULL, revision INTEGER NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(kind, period_start)
            );
            CREATE TABLE IF NOT EXISTS report_files (
                report_id TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                file_id TEXT NOT NULL REFERENCES files(id),
                position INTEGER NOT NULL, PRIMARY KEY(report_id,file_id)
            );
            CREATE TABLE IF NOT EXISTS drafts (
                kind TEXT NOT NULL, date TEXT NOT NULL, content TEXT NOT NULL,
                PRIMARY KEY(kind,date)
            );
            CREATE INDEX IF NOT EXISTS reports_period ON reports(period_start,kind);
            CREATE INDEX IF NOT EXISTS files_date ON files(date,created_at,id);
            """)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.database, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            with con:
                yield con
        finally:
            con.close()

    def get_setting(self, key, default=None):
        with self.connect() as con:
            row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key, value):
        self.set_settings({key: value})

    def set_settings(self, values):
        with self.connect() as con:
            con.executemany("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            [(key, json.dumps(value, ensure_ascii=False)) for key, value in values.items()])

    def add_file(self, info):
        with self.connect() as con:
            con.execute("INSERT INTO files(id,name,date,size,media_type,sha256,created_at) VALUES (?,?,?,?,?,?,?)",
                        tuple(info[k] for k in ["id", "name", "date", "size", "media_type", "sha256", "created_at"]))
        return self.get_file(info["id"])

    def get_file(self, file_id, internal=False):
        with self.connect() as con:
            row = con.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        if internal:
            data["analysis"] = json.loads(data["analysis"]) if data["analysis"] else None
        else:
            data.pop("analysis")
            data.pop("analysis_model")
            data["download_url"] = f"/api/files/{data['id']}/download"
        return data

    def list_files(self, report_date):
        with self.connect() as con:
            rows = con.execute("SELECT id FROM files WHERE date=? ORDER BY created_at,id", (report_date,)).fetchall()
        return [self.get_file(row["id"]) for row in rows]

    def cache_analysis(self, file_id, analysis, model):
        with self.connect() as con:
            con.execute("UPDATE files SET analysis=?,analysis_model=? WHERE id=?",
                        (json.dumps(analysis, ensure_ascii=False), model, file_id))

    def report(self, kind, period_start):
        with self.connect() as con:
            con.execute("BEGIN")
            row = con.execute("SELECT * FROM reports WHERE kind=? AND period_start=?", (kind, period_start)).fetchone()
            if not row:
                return None
            return self._hydrate_reports(con, [row])[0]

    @staticmethod
    def _hydrate_reports(con, rows):
        reports = []
        for row in rows:
            data = json.loads(row["content"])
            data.update({k: row[k] for k in ["id", "kind", "date", "period_start", "period_end", "revision", "created_at", "updated_at"]})
            data["files"] = []
            reports.append(data)
        by_id = {r["id"]: r for r in reports}
        ids = list(by_id)
        for offset in range(0, len(ids), 500):
            batch = ids[offset:offset + 500]
            attached = con.execute(
                "SELECT rf.report_id,f.id,f.name,f.date,f.size,f.media_type,f.sha256,f.created_at "
                "FROM report_files rf JOIN files f ON f.id=rf.file_id "
                f"WHERE rf.report_id IN ({','.join('?' for _ in batch)}) ORDER BY rf.report_id,rf.position", batch)
            for row in attached:
                item = dict(row)
                report_id = item.pop("report_id")
                item["download_url"] = f"/api/files/{item['id']}/download"
                by_id[report_id]["files"].append(item)
        return reports

    def search_reports(self, kind=None, start=None, end=None, query=None, on_date=None, limit=100, offset=0):
        where, args = ["1=1"], []
        for column, value, op in [("kind", kind, "="), ("period_start", start, ">="), ("period_start", end, "<=")]:
            if value is not None:
                where.append(f"{column}{op}?")
                args.append(value)
        if on_date is not None:
            where.extend(["period_start<=?", "period_end>=?"])
            args.extend([on_date, on_date])
        with self.connect() as con:
            # Keep the count, page and attachments in one read snapshot.
            con.execute("BEGIN")
            clause = " WHERE " + " AND ".join(where)
            total = con.execute("SELECT COUNT(*) FROM reports" + clause, args).fetchone()[0]
            sql = "SELECT * FROM reports" + clause + " ORDER BY period_start DESC,kind"
            page_args = args.copy()
            if limit is not None and not query:
                sql += " LIMIT ? OFFSET ?"
                page_args.extend([limit, offset])
            reports = self._hydrate_reports(con, con.execute(sql, page_args).fetchall())
        if query:  # Legacy keyword API includes attachment names, so filter after hydration.
            reports = [r for r in reports if query.casefold() in json.dumps(r, ensure_ascii=False).casefold()]
            total = len(reports)
            reports = reports[offset:offset + limit] if limit is not None else reports[offset:]
        return {"items": reports, "total": total, "limit": limit, "offset": offset}

    def list_reports(self, kind=None, start=None, end=None, query=None, on_date=None):
        return self.search_reports(kind, start, end, query, on_date, limit=None)["items"]

    def save_report(self, kind, anchor, start, end, content, file_ids, expected_revision, expected_sources=None):
        report_id, now = f"{kind}:{start}", timestamp()
        with self.connect() as con:
            # Acquire the write lock before checking the revision.
            con.execute("BEGIN IMMEDIATE")
            current = con.execute("SELECT revision FROM reports WHERE id=?", (report_id,)).fetchone()
            revision = current["revision"] if current else 0
            if expected_revision is not None and expected_revision != revision:
                raise ConflictError("汇报已在其他页面更新，请重新打开后再保存。")
            if kind == "weekly":
                sources = con.execute("SELECT id,revision FROM reports WHERE kind='daily' AND period_start>=? AND period_start<=?",
                                      (start, end)).fetchall()
                revisions = {r["id"]: r["revision"] for r in sources}
                if expected_sources is not None and revisions != expected_sources:
                    raise ConflictError("日报来源已更新，请重新生成周报后再保存。")
                content["source_revisions"] = revisions
                rows = con.execute("""
                    SELECT rf.file_id FROM report_files rf JOIN reports r ON r.id=rf.report_id
                    WHERE r.kind='daily' AND r.period_start>=? AND r.period_start<=?
                    ORDER BY r.date,rf.position
                """, (start, end)).fetchall()
                file_ids = [r["file_id"] for r in rows]
            con.execute("""
                INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET date=excluded.date,content=excluded.content,
                    revision=excluded.revision,updated_at=excluded.updated_at
            """, (report_id, kind, anchor, start, end, json.dumps(content, ensure_ascii=False),
                  revision + 1, now, now))
            con.execute("DELETE FROM report_files WHERE report_id=?", (report_id,))
            con.executemany("INSERT INTO report_files VALUES (?,?,?)",
                            [(report_id, f, i) for i, f in enumerate(dict.fromkeys(file_ids))])
            con.execute("DELETE FROM drafts WHERE kind=? AND date IN (?,?)", (kind, anchor, start))
        return self.report(kind, start)

    def save_draft(self, kind, report_date, content):
        with self.connect() as con:
            con.execute("INSERT INTO drafts VALUES (?,?,?) ON CONFLICT(kind,date) DO UPDATE SET content=excluded.content",
                        (kind, report_date, json.dumps(content, ensure_ascii=False)))

    def get_draft(self, kind, report_date):
        with self.connect() as con:
            row = con.execute("SELECT content FROM drafts WHERE kind=? AND date=?", (kind, report_date)).fetchone()
        return json.loads(row["content"]) if row else None
