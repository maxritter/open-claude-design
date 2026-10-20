"""Artifact asset store, comment threads, and shared database over the frame protocol."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from typing import Any

from open_claude_design.artifact_api import (
    ArtifactClient,
    ArtifactConflict,
    ArtifactHTTPError,
    ArtifactOutcomeUnknown,
    ArtifactSnapshot,
    _clean,
    artifact_id,
    artifact_url,
)
from open_claude_design.config import (
    ARTIFACT_API_PREFIX,
    ARTIFACT_ASSET_CONTENT_TYPES,
    ARTIFACT_ASSET_LIST_LIMIT,
    ARTIFACT_ASSET_UPLOAD_TIMEOUT_SECONDS,
    ARTIFACT_DB_LEVELS,
    ARTIFACT_DB_MAX_BATCH,
    ARTIFACT_DB_MAX_BATCH_BYTES,
    ARTIFACT_DB_MAX_LIMIT,
    ARTIFACT_DB_MAX_PATH_BYTES,
    ARTIFACT_DB_MAX_WHERE,
    ARTIFACT_DB_QUERY_OPERATORS,
    ARTIFACT_MAX_ASSET_BYTES,
    ARTIFACT_MAX_ASSET_COPY,
    ARTIFACT_MAX_COMMENT_BYTES,
    ARTIFACT_MAX_SVG_ASSET_BYTES,
)
from open_claude_design.errors import ClaudeDesignProtocolError, ClaudeDesignSafetyError

ASSET_ID = re.compile(r"[0-9a-f]{32}")
THREAD_ID = re.compile(r"[0-9a-z]{1,128}")
CURSOR = re.compile(r"[A-Za-z0-9_=-]{1,4096}")
SEGMENT = r"(?!\.\.?(?:/|$))[A-Za-z0-9_\-.~:@+]{1,200}"
DOC_ID = re.compile(SEGMENT)
COLLECTION = re.compile(rf"{SEGMENT}(?:/{SEGMENT}){{0,14}}")
FIELD = re.compile(r'(?!__.*__$)[^\x00-\x1f"\\./\[\]]{1,200}')
DEFINITE_REFUSALS = frozenset({400, 404, 409, 412, 413, 422, 429})


def _require_writer(snapshot: ArtifactSnapshot) -> None:
    if snapshot.role not in {"owner", "writer"}:
        raise ClaudeDesignSafetyError("This change needs edit access to the artifact.")


def asset_content_type(name: str) -> str:
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    mime = ARTIFACT_ASSET_CONTENT_TYPES.get(suffix)
    if mime is None:
        raise ClaudeDesignSafetyError("Assets accept " + ", ".join(sorted(ARTIFACT_ASSET_CONTENT_TYPES)) + " files.")
    return mime


def _asset_row(row: dict[str, Any]) -> dict[str, Any]:
    asset = row.get("opaque_id")
    if not isinstance(asset, str) or ASSET_ID.fullmatch(asset) is None:
        raise ClaudeDesignProtocolError("Asset store returned an invalid asset id.")
    return {
        "id": asset,
        "url": f"/_blob/{asset}",
        "content_type": row.get("content_type"),
        "bytes": row.get("size_bytes"),
        **({"sha256": row["sha256"]} if isinstance(row.get("sha256"), str) else {}),
        **({"created_at": row["created_at"]} if isinstance(row.get("created_at"), str) else {}),
    }


class ArtifactAssets:
    def __init__(self, client: ArtifactClient) -> None:
        self.client = client

    def upload(self, snapshot: ArtifactSnapshot, name: str, data: bytes) -> dict[str, Any]:
        _require_writer(snapshot)
        mime = asset_content_type(name)
        limit = ARTIFACT_MAX_SVG_ASSET_BYTES if mime == "image/svg+xml" else ARTIFACT_MAX_ASSET_BYTES
        if not data or len(data) > limit:
            raise ClaudeDesignSafetyError(f"Assets must be 1 byte to {limit >> 20} MiB for this file type.")
        self.client.require_write_window()
        result = self.client.request(
            "POST",
            f"{ARTIFACT_API_PREFIX}blob/{snapshot.id}/agent-upload",
            body=data,
            content_type=mime,
            timeout=ARTIFACT_ASSET_UPLOAD_TIMEOUT_SECONDS,
        )
        if not isinstance(result, dict):
            raise ArtifactOutcomeUnknown("Asset upload returned no evidence; list assets before retrying.")
        try:
            row = _asset_row(result)
        except ClaudeDesignProtocolError as error:
            raise ArtifactOutcomeUnknown("Asset upload reply was unreadable; list assets before retrying.") from error
        digest = hashlib.sha256(data).hexdigest()
        if row["content_type"] != mime or (mime != "image/svg+xml" and row["bytes"] != len(data)):
            raise ArtifactOutcomeUnknown("Asset upload echo does not match the sent file; list assets to reconcile.")
        if "sha256" in row and mime != "image/svg+xml" and row["sha256"] != digest:
            raise ArtifactOutcomeUnknown("Asset upload hash does not match the sent file; list assets to reconcile.")
        return {
            "backend": "artifact",
            "id": snapshot.id,
            "asset": row,
            "reference": row["url"],
            "local_sha256": digest,
            "verified": True,
            "mutated": True,
        }

    def list(self, value: str, *, after: str | None = None, all_pages: bool = True) -> dict[str, Any]:
        value = artifact_id(value)
        assets: list[dict[str, Any]] = []
        usage: dict[str, Any] = {}
        cursor = after
        seen: set[str] = set()
        for _page in range(200):
            if cursor is not None and CURSOR.fullmatch(cursor) is None:
                raise ValueError("Use the next value from an earlier asset listing.")
            payload = {"limit": ARTIFACT_ASSET_LIST_LIMIT, **({"after": cursor} if cursor else {})}
            result = self.client.request(
                "POST", f"{ARTIFACT_API_PREFIX}blob/{value}/agent-list", payload, mutation=False
            )
            if not isinstance(result, dict) or not isinstance(result.get("assets"), list):
                raise ClaudeDesignProtocolError("Asset listing is incomplete.")
            assets.extend(_asset_row(row) for row in result["assets"] if isinstance(row, dict))
            reported = result.get("usage")
            usage = reported if isinstance(reported, dict) else {}
            cursor = result.get("next") or None
            if not all_pages or cursor is None:
                break
            if cursor in seen:
                raise ClaudeDesignProtocolError("Asset listing repeated its cursor.")
            seen.add(cursor)
        return {
            "backend": "artifact",
            "id": value,
            "assets": assets,
            "usage": {
                "files": usage.get("files"),
                "bytes": usage.get("bytes"),
                "max_files": usage.get("max_files"),
                "max_bytes": usage.get("max_bytes"),
            },
            **({"next": cursor} if cursor and not all_pages else {}),
        }

    def delete(self, snapshot: ArtifactSnapshot, asset: str) -> dict[str, Any]:
        _require_writer(snapshot)
        if ASSET_ID.fullmatch(asset) is None:
            raise ValueError("Asset ids are 32 lowercase hexadecimal characters.")
        self.client.require_write_window()
        result = self.client.request("POST", f"{ARTIFACT_API_PREFIX}blob/{snapshot.id}/{asset}/agent-delete", {})
        if not isinstance(result, dict) or not isinstance(result.get("deleted"), bool):
            raise ArtifactOutcomeUnknown("Asset delete reply was unreadable; list assets to check.")
        return {"backend": "artifact", "id": snapshot.id, "asset": asset, "deleted": result["deleted"], "mutated": True}

    def copy(self, snapshot: ArtifactSnapshot, source: str, assets: list[str]) -> dict[str, Any]:
        _require_writer(snapshot)
        source = artifact_id(source)
        if source == snapshot.id:
            raise ValueError("The source artifact is the destination; its assets are already there.")
        if not assets or len(assets) > ARTIFACT_MAX_ASSET_COPY or len(set(assets)) != len(assets):
            raise ValueError(f"Copy 1–{ARTIFACT_MAX_ASSET_COPY} distinct asset ids per call.")
        if any(ASSET_ID.fullmatch(asset) is None for asset in assets):
            raise ValueError("Asset ids are 32 lowercase hexadecimal characters.")
        self.client.require_write_window()
        result = self.client.request(
            "POST",
            f"{ARTIFACT_API_PREFIX}blob/{snapshot.id}/agent-copy",
            {"from": source, "ids": assets},
            timeout=ARTIFACT_ASSET_UPLOAD_TIMEOUT_SECONDS,
        )
        rows = result.get("assets") if isinstance(result, dict) else None
        if (
            not isinstance(rows, list)
            or len(rows) != len(assets)
            or any(not isinstance(row, dict) or row.get("from_id") != assets[i] for i, row in enumerate(rows))
        ):
            raise ArtifactOutcomeUnknown("Asset copy reply was unreadable; list the destination before retrying.")
        return {
            "backend": "artifact",
            "id": snapshot.id,
            "from": source,
            "assets": [{"from_id": row["from_id"], **_asset_row(row)} for row in rows],
            "verified": True,
            "mutated": True,
        }


def _anchor(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    anchor = {
        "path": raw.get("path") if isinstance(raw.get("path"), str) else None,
        "label": _clean(raw.get("label")),
        "detail": _clean(raw.get("detail")),
        "quote": _clean(raw.get("span", {}).get("text") if isinstance(raw.get("span"), dict) else None, 400),
        "region": raw.get("region") if isinstance(raw.get("region"), dict) else None,
    }
    return {key: value for key, value in anchor.items() if value is not None}


class ArtifactComments:
    def __init__(self, client: ArtifactClient) -> None:
        self.client = client

    def read(self, value: str, *, thread: str | None = None) -> dict[str, Any]:
        value = artifact_id(value)
        result = self.client.request("GET", f"{ARTIFACT_API_PREFIX}comments/{value}?names=1")
        if not isinstance(result, dict) or not isinstance(result.get("threads"), list):
            raise ClaudeDesignProtocolError("Comment threads are unavailable for this artifact.")
        viewer = result.get("viewer")
        listed = result.get("names")
        names: dict[str, Any] = listed if isinstance(listed, dict) else {}
        threads = []
        for row in result["threads"]:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                continue
            if thread is not None and row["id"] != thread:
                continue
            activated = row.get("claude_activated_at")
            comments = []
            for comment in row.get("comments") or []:
                if not isinstance(comment, dict) or not isinstance(comment.get("text"), str):
                    continue
                raw_author = comment.get("author")
                author: dict[str, Any] = raw_author if isinstance(raw_author, dict) else {}
                account = author.get("account")
                comments.append(
                    {
                        "id": comment.get("id"),
                        "author": account,
                        "author_name": _clean(names.get(account)) if isinstance(account, str) else None,
                        "author_role": author.get("role"),
                        "author_is_you": isinstance(account, str) and account == viewer,
                        "text": comment["text"],
                        "created_at": comment.get("created_at"),
                        "sent_to_claude": bool(comment.get("to_claude_at")),
                        "posted_by_claude": comment.get("source") == "agent" or author.get("role") == "agent",
                    }
                )
            threads.append(
                {
                    "id": row["id"],
                    "created_at": row.get("created_at"),
                    "resolved": bool(row.get("resolved_at")),
                    "activated_for_claude": bool(activated) and activated != "degraded",
                    "activated_by": row.get("claude_activated_by"),
                    "anchor": _anchor(row.get("anchor")),
                    "comments": comments,
                }
            )
        if thread is not None and not threads:
            raise ArtifactHTTPError("That comment thread does not exist on this artifact.", status=404)
        return {
            "backend": "artifact",
            "id": value,
            "url": artifact_url(value),
            "viewer": viewer,
            "threads": threads,
            "untrusted": True,
        }

    def _thread(self, value: str, thread: str) -> dict[str, Any]:
        if THREAD_ID.fullmatch(thread) is None:
            raise ValueError("Use a thread id from `artifacts comments list`.")
        return self.read(value, thread=thread)["threads"][0]

    def reply(self, value: str, thread: str, text: str) -> dict[str, Any]:
        value = artifact_id(value)
        if not text.strip() or len(text.encode()) > ARTIFACT_MAX_COMMENT_BYTES:
            raise ValueError("A reply is 1–4096 bytes of plain text.")
        row = self._thread(value, thread)
        if not row["activated_for_claude"]:
            raise ClaudeDesignSafetyError(
                "That thread was not sent to Claude. Ask someone who can edit the artifact to use Send to Claude "
                "or mention @claude on it; nothing was posted."
            )
        self.client.require_write_window()
        result = self.client.request(
            "POST",
            f"{ARTIFACT_API_PREFIX}comments/{value}/{thread}",
            {"id": str(uuid.uuid4()), "text": text, "answers_summon": True},
        )
        comment = result.get("comment_id") if isinstance(result, dict) else None
        if not isinstance(comment, str) or result.get("thread_id") != thread:
            raise ArtifactOutcomeUnknown("Reply outcome is unknown; re-read the thread before retrying.")
        return {
            "backend": "artifact",
            "id": value,
            "thread": thread,
            "comment": comment,
            "replayed": result.get("replayed") is True,
            "mutated": True,
        }

    def resolve(self, value: str, thread: str) -> dict[str, Any]:
        value = artifact_id(value)
        row = self._thread(value, thread)
        if row["resolved"]:
            return {"backend": "artifact", "id": value, "thread": thread, "resolved": True, "unchanged": True}
        if not row["activated_for_claude"]:
            raise ClaudeDesignSafetyError(
                "Only threads sent to Claude can be resolved from here; leave it open for a person to resolve."
            )
        version = self.client.versions(value).get("live")
        self.client.require_write_window()
        try:
            self.client.request(
                "POST",
                f"{ARTIFACT_API_PREFIX}comments/{value}/{thread}/resolve",
                {"resolved": True, "after_version": version},
            )
        except ArtifactOutcomeUnknown as error:
            raise ArtifactConflict(
                "The artifact changed since that version, or the resolve is unsettled; re-read and retry once."
            ) from error
        return {"backend": "artifact", "id": value, "thread": thread, "resolved": True, "mutated": True}


def _collection(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > ARTIFACT_DB_MAX_PATH_BYTES
        or COLLECTION.fullmatch(value) is None
        or value.count("/") % 2 != 0
    ):
        raise ValueError(
            "A collection path has an odd number of /-separated segments (collection/document/collection); "
            "per-user data lives under data/users/<id or me>."
        )
    return value


def _document(collection: str, doc_id: str) -> str:
    if DOC_ID.fullmatch(doc_id) is None:
        raise ValueError("A document id is one path segment.")
    path = f"{_collection(collection)}/{doc_id}"
    if len(path) > ARTIFACT_DB_MAX_PATH_BYTES:
        raise ValueError("The document path exceeds 1000 bytes.")
    return path


class ArtifactDatabase:
    def __init__(self, client: ArtifactClient) -> None:
        self.client = client
        self._me: dict[str, str] = {}

    def call(
        self, value: str, verb: str, args: dict[str, Any], *, as_level: str | None = None, write: bool = False
    ) -> dict[str, Any]:
        value = artifact_id(value)
        if as_level is not None and as_level not in ARTIFACT_DB_LEVELS:
            raise ValueError("--as-level is view, interact, or admin.")
        payload = {
            "slug": value,
            "verb": verb,
            "args": args,
            **({"asLevel": as_level} if as_level else {}),
            **({"requireVersion": True} if write and verb != "str_replace" else {}),
        }
        if write and len(json.dumps(payload, ensure_ascii=False).encode()) > ARTIFACT_DB_MAX_BATCH_BYTES:
            raise ClaudeDesignSafetyError("A database request is limited to 1 MiB.")
        result = self.client.request(
            "POST",
            f"{ARTIFACT_API_PREFIX}db/agent",
            payload,
            mutation=write,
            timeout=60 if write else 30,
            allow_status=DEFINITE_REFUSALS,
        )
        if not isinstance(result, dict):
            raise ClaudeDesignProtocolError("Database answer is not an object.")
        status = result.get("__status__")
        if status is not None:
            code = result.get("code") or "refused"
            detail = result.get("message") or code
            if code == "version_mismatch":
                raise ArtifactConflict(f"Nothing was written: {detail}.")
            if code == "not_declared" or (verb == "whoami" and status in {400, 403}):
                raise ClaudeDesignSafetyError(
                    "The artifact does not declare what this needs (db for documents, user for data/users/me)."
                )
            if code in {"edit_no_match", "edit_ambiguous", "edit_field_missing", "edit_field_not_string"}:
                raise ValueError(f"Nothing was written: {detail}.")
            raise ArtifactHTTPError(
                f"Database refused the {verb} (HTTP {status}, {code}): {detail}.", status=status, code=code
            )
        return result

    def whoami(self, value: str) -> str:
        value = artifact_id(value)
        if value not in self._me:
            result = self.call(value, "whoami", {})
            if not isinstance(result.get("id"), str) or DOC_ID.fullmatch(result["id"]) is None:
                raise ClaudeDesignProtocolError("Database identity reply is malformed.")
            self._me[value] = result["id"]
        return self._me[value]

    def _resolve_me(self, value: str, collection: str) -> str:
        parts = collection.split("/")
        if len(parts) >= 3 and parts[:2] == ["data", "users"] and parts[2] == "me":
            parts[2] = self.whoami(value)
        return "/".join(parts)

    @staticmethod
    def _envelope(value: str, result: dict[str, Any], **extra: Any) -> dict[str, Any]:
        return {
            "backend": "artifact",
            "id": value,
            **extra,
            **({"authored_by_others": True} if result.get("authoredByOthers") else {}),
            "untrusted": True,
        }

    def get(self, value: str, collection: str, doc_id: str, *, as_level: str | None = None) -> dict[str, Any]:
        value = artifact_id(value)
        path = _document(self._resolve_me(value, collection), doc_id)
        result = self.call(value, "get", {"path": path}, as_level=as_level)
        return self._envelope(
            value,
            result,
            path=path,
            exists=result.get("exists") is True,
            data=result.get("data"),
            version=result.get("version"),
            updated_at=result.get("updatedAt"),
        )

    def list(
        self,
        value: str,
        collection: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        where: list[list[Any]] | None = None,
        order_by: dict[str, str] | None = None,
        as_level: str | None = None,
    ) -> dict[str, Any]:
        value = artifact_id(value)
        collection = _collection(self._resolve_me(value, collection))
        if limit is not None and not 1 <= limit <= ARTIFACT_DB_MAX_LIMIT:
            raise ValueError("limit is 1–1000.")
        args: dict[str, Any] = {
            "collection": collection,
            **({"limit": limit} if limit else {}),
            **({"cursor": cursor} if cursor else {}),
        }
        verb = "list"
        if where or order_by:
            verb = "query"
            clauses = where or []
            if len(clauses) > ARTIFACT_DB_MAX_WHERE:
                raise ValueError("A query takes at most 10 where clauses.")
            parsed = []
            for clause in clauses:
                if (
                    not isinstance(clause, list)
                    or len(clause) != 3
                    or not isinstance(clause[0], str)
                    or clause[1] not in ARTIFACT_DB_QUERY_OPERATORS
                ):
                    raise ValueError("Each where clause is [field, operator, value].")
                parsed.append({"field": clause[0], "op": ARTIFACT_DB_QUERY_OPERATORS[clause[1]], "value": clause[2]})
            if parsed:
                args["where"] = parsed
            if order_by:
                if not isinstance(order_by.get("field"), str) or order_by.get("direction") not in {None, "asc", "desc"}:
                    raise ValueError("order_by is {field, direction: asc|desc}.")
                args["orderBy"] = {key: item for key, item in order_by.items() if item is not None}
        result = self.call(value, verb, args, as_level=as_level)
        docs = result.get("docs")
        if not isinstance(docs, list):
            raise ClaudeDesignProtocolError("Database listing is incomplete.")
        return self._envelope(
            value,
            result,
            collection=collection,
            docs=[
                {
                    "id": doc.get("id"),
                    "data": doc.get("data"),
                    "version": doc.get("version"),
                    "updated_at": doc.get("updatedAt"),
                }
                for doc in docs
                if isinstance(doc, dict)
            ],
            next_cursor=result.get("nextCursor") or None,
        )

    def _write_args(
        self, op: str, path: str, data: dict[str, Any] | None, if_version: int | None, edit: dict[str, Any] | None
    ) -> dict[str, Any]:
        pinned = {"ifVersion": if_version} if if_version is not None else {}
        if op == "delete":
            return {"path": path, **pinned}
        if op == "str_replace":
            if edit is None or FIELD.fullmatch(str(edit.get("field", ""))) is None:
                raise ValueError("str-replace needs a plain top-level --field.")
            if not isinstance(edit.get("old"), str) or not edit["old"] or not isinstance(edit.get("new"), str):
                raise ValueError("str-replace needs --old (non-empty) and --new text.")
            return {
                "path": path,
                "field": edit["field"],
                "old_str": edit["old"],
                "new_str": edit["new"],
                **({"replace_all": True} if edit.get("replace_all") else {}),
                "idem": secrets.token_urlsafe(16),
                **pinned,
            }
        if not isinstance(data, dict):
            raise ValueError("set and update take a JSON object document.")
        if op == "set" and "__delete__" in json.dumps(data):
            raise ValueError('set replaces the whole document; remove a field with update and {"__delete__": true}.')
        return {"path": path, "data": data, **({"replace": True} if op == "set" else {}), **pinned}

    def write(
        self,
        value: str,
        op: str,
        collection: str,
        doc_id: str,
        *,
        data: dict[str, Any] | None = None,
        if_version: int | None = None,
        edit: dict[str, Any] | None = None,
        as_level: str | None = None,
    ) -> dict[str, Any]:
        value = artifact_id(value)
        if op not in {"set", "update", "delete", "str_replace"}:
            raise ValueError("Database writes are set, update, delete, or str_replace.")
        self.client.require_write_window()
        path = _document(self._resolve_me(value, collection), doc_id)
        result = self.call(value, op, self._write_args(op, path, data, if_version, edit), as_level=as_level, write=True)
        return self._envelope(
            value, result, path=path, op=op, version=result.get("version"), usage=result.get("usage"), mutated=True
        )

    def batch(self, value: str, writes: list[dict[str, Any]], *, as_level: str | None = None) -> dict[str, Any]:
        value = artifact_id(value)
        if not isinstance(writes, list) or not 1 <= len(writes) <= ARTIFACT_DB_MAX_BATCH:
            raise ValueError("A batch takes 1–50 writes.")
        self.client.require_write_window()
        ops, seen = [], set()
        for number, entry in enumerate(writes, 1):
            if not isinstance(entry, dict) or entry.get("op") not in {"set", "update", "delete"}:
                raise ValueError(f"Write {number}: op is set, update, or delete.")
            path = _document(self._resolve_me(value, str(entry.get("collection", ""))), str(entry.get("doc_id", "")))
            if path in seen:
                raise ValueError(f"Write {number} addresses {path} twice; a batch writes each document once.")
            seen.add(path)
            version = entry.get("if_version")
            if version is not None and (not isinstance(version, int) or isinstance(version, bool) or version < 1):
                raise ValueError(f"Write {number}: if_version is a positive integer.")
            ops.append({"op": entry["op"], **self._write_args(entry["op"], path, entry.get("data"), version, None)})
        result = self.call(value, "batch", {"ops": ops}, as_level=as_level, write=True)
        results = result.get("results")
        if not isinstance(results, list) or len(results) != len(ops):
            raise ArtifactOutcomeUnknown("Batch outcome is incomplete; read the documents back before retrying.")
        return self._envelope(
            value,
            result,
            writes=[
                {"path": op["path"], "op": op["op"], "version": row.get("version")}
                for op, row in zip(ops, results, strict=True)
                if isinstance(row, dict)
            ],
            usage=result.get("usage"),
            mutated=True,
        )
