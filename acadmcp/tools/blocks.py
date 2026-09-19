"""Blocks, their attributes, and external references."""

from __future__ import annotations

import fnmatch
import math
import os
from collections import Counter
from typing import Any

from .. import com, lisp, util
from ..errors import AcadError, NotFound
from ..registry import tool


def _find_block(doc: Any, name: str) -> Any:
    target = str(name).lower()

    def scan() -> Any:
        for i in range(int(doc.Blocks.Count)):
            block = doc.Blocks.Item(i)
            if str(block.Name).lower() == target:
                return block
        return None

    found = com.retry(scan, timeout=30, attr_is_busy=True, context="finding the block")
    if found is None:
        raise NotFound(f"There is no block called {name!r} in {doc.Name}.")
    return found


@tool(readonly=True, description="List the block definitions in a drawing, with how many times each is inserted.")
def block_list(
    pattern: str | None = None,
    include_xrefs: bool = True,
    only_used: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    used = Counter(
        str(n)
        for n in (
            lisp.evaluate(
                lisp.raw(
                    '(progn (setq amq-ss (ssget "_X" (list (cons 0 "INSERT"))) amq-i 0 amq-out nil)'
                    " (if amq-ss (repeat (sslength amq-ss)"
                    " (setq amq-out (cons (cdr (assoc 2 (entget (ssname amq-ss amq-i))))"
                    " amq-out) amq-i (1+ amq-i)))) (reverse amq-out))"
                ),
                timeout=300,
            )
            or []
        )
    )

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        rows = []
        for i in range(int(doc.Blocks.Count)):
            block = doc.Blocks.Item(i)
            name = str(block.Name)
            if name.startswith("*"):
                continue  # anonymous / model space / paper space
            is_xref = bool(com.quiet(lambda: block.IsXRef, False))
            if is_xref and not include_xrefs:
                continue
            count = used.get(name, 0)
            if only_used and not count:
                continue
            if pattern and not fnmatch.fnmatch(name.lower(), str(pattern).lower()):
                continue
            row: dict[str, Any] = {
                "name": name,
                "inserted": count,
                "entities": int(com.quiet(lambda: block.Count, 0) or 0),
            }
            if is_xref:
                row["xref"] = str(com.quiet(lambda: block.Path, "") or "")
            layout = com.quiet(lambda: block.IsLayout, False)
            if layout:
                continue
            rows.append(row)
        rows.sort(key=lambda r: (-r["inserted"], r["name"].lower()))
        return {"count": len(rows), "blocks": rows}

    return com.run_com(work, timeout=180)


@tool(description=(
    "Create a block definition from existing entities. Optionally add attribute "
    "definitions, each {\"tag\": \"...\", \"prompt\": \"...\", \"default\": \"...\", "
    "\"position\": [x,y], \"height\": 2.5}."
))
def block_define(
    name: str,
    handles: list[str],
    base_point: list[float],
    attributes: list[dict[str, Any]] | None = None,
    keep_source: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    if not handles:
        raise AcadError("a block needs at least one entity")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        existing = None
        try:
            existing = _find_block(doc, name)
        except NotFound:
            pass
        if existing is not None:
            raise AcadError(
                f"A block called {name!r} already exists. Delete it first, or "
                "insert it instead."
            )
        block = com.retry(lambda: doc.Blocks.Add(com.pt(base_point), str(name)))
        sources = com.by_handles(doc, handles)
        com.retry(lambda: doc.CopyObjects(com.objects(sources), block))
        for spec in attributes or []:
            tag = str(spec.get("tag") or "").strip()
            if not tag:
                raise AcadError("every attribute needs a tag")
            com.retry(
                lambda s=spec, t=tag: block.AddAttribute(
                    float(s.get("height", 2.5)),
                    0,  # acAttributeModeNormal
                    str(s.get("prompt", t)),
                    com.pt(s.get("position", base_point)),
                    t,
                    str(s.get("default", "")),
                )
            )
        if not keep_source:
            for ent in sources:
                com.quiet(lambda e=ent: e.Delete())
        return {
            "block": str(block.Name),
            "entities": int(com.quiet(lambda: block.Count, 0) or 0),
            "attributes": [str(a.get("tag")) for a in attributes or []],
            "source_kept": bool(keep_source),
        }

    return com.run_com(work, timeout=300)


@tool(description=(
    "Insert a block. Use `name` for a block already in the drawing, or `file` "
    "for an external .dwg. Set attribute values with a {TAG: value} dictionary."
))
def block_insert(
    name: str | None = None,
    file: str | None = None,
    position: list[float] | None = None,
    positions: list[list[float]] | None = None,
    scale: float = 1.0,
    scale_xyz: list[float] | None = None,
    rotation: float = 0.0,
    attributes: dict[str, Any] | None = None,
    layer: str | None = None,
    space: str = "auto",
    drawing: str | None = None,
) -> dict[str, Any]:
    if not name and not file:
        raise AcadError("give a block name or a .dwg file to insert")
    places = positions or ([position] if position else None)
    if not places:
        raise AcadError("give a position (or several in positions)")

    source = str(file) if file else str(name)
    if file:
        source = os.path.abspath(os.path.expanduser(source))
        if not os.path.isfile(source):
            raise AcadError(f"There is no file at {source}")

    sx, sy, sz = (scale_xyz + [1.0, 1.0, 1.0])[:3] if scale_xyz else (scale, scale, scale)

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        target = com.space(doc, space)
        if layer:
            util.ensure_layer(doc, layer)
        made = []
        for p in places:
            ref = com.retry(
                lambda p=p: target.InsertBlock(
                    com.pt(p), source, float(sx), float(sy), float(sz),
                    math.radians(float(rotation)),
                ),
                timeout=180,
                context=f"inserting {source}",
            )
            if layer:
                ref.Layer = str(layer)
            if attributes:
                _set_attributes(ref, attributes)
            made.append(util.describe(ref))
        return {"created": made, "count": len(made), "block": source}

    return com.run_com(work, timeout=300)


def _set_attributes(ref: Any, values: dict[str, Any]) -> list[str]:
    wanted = {str(k).upper(): v for k, v in values.items()}
    changed = []
    for att in com.unwrap(com.quiet(lambda: ref.GetAttributes(), []) or []):
        tag = str(att.TagString).upper()
        if tag in wanted:
            att.TextString = str(wanted[tag])
            changed.append(tag)
    return changed


@tool(description="Read or write the attribute values of block references. Pass set_values to change them, e.g. {\"STRING\": \"S1\"}.")
def block_attributes(
    handles: list[str] | None = None,
    block: str | None = None,
    set_values: dict[str, Any] | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    if not handles and not block:
        raise AcadError("give handles, or a block name to find every insert of it")

    if not handles:
        handles = [
            str(h)
            for h in (
                lisp.evaluate(
                    lisp.raw(
                        '(acadmcp:handles (ssget "_X" (list (cons 0 "INSERT") '
                        f"(cons 2 {lisp.lstr(str(block))}))))"
                    ),
                    timeout=300,
                )
                or []
            )
        ]
        if not handles:
            raise NotFound(f"No inserts of block {block!r} were found.")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        rows = []
        updated = 0
        for h in handles:
            ref = com.by_handle(doc, str(h))
            if util.dxf_type(ref) != "INSERT":
                continue
            if set_values:
                if _set_attributes(ref, set_values):
                    updated += 1
            rows.append(
                {
                    "handle": str(ref.Handle),
                    "block": str(com.quiet(lambda: ref.Name, "")),
                    "attributes": {
                        str(a.TagString): str(a.TextString)
                        for a in com.unwrap(com.quiet(lambda: ref.GetAttributes(), []) or [])
                    },
                }
            )
        out: dict[str, Any] = {"count": len(rows), "inserts": rows}
        if set_values:
            out["updated"] = updated
        return out

    return com.run_com(work, timeout=300)


@tool(description="Rename or delete a block definition, or replace its contents with another drawing (redefine).")
def block_edit(
    name: str,
    rename_to: str | None = None,
    delete: bool = False,
    redefine_from_file: str | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    if redefine_from_file:
        path = os.path.abspath(os.path.expanduser(str(redefine_from_file)))
        if not os.path.isfile(path):
            raise AcadError(f"There is no file at {path}")
        lisp.evaluate(
            lisp.command("_.-INSERT", f"{name}={path.replace(chr(92), '/')}", "_Y", None),
            timeout=300,
        )
        lisp.cancel()
        return {"redefined": name, "from": path}

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        block = _find_block(doc, name)
        if rename_to:
            block.Name = str(rename_to)
            return {"renamed": {"from": name, "to": str(rename_to)}}
        if delete:
            com.retry(lambda: block.Delete())
            return {"deleted": name}
        raise AcadError("say what to do: rename_to, delete, or redefine_from_file")

    return com.run_com(work, timeout=180)


@tool(description="Write entities (or a whole block) out to a separate .dwg file - the WBLOCK command.")
def block_export(
    path: str,
    handles: list[str] | None = None,
    block: str | None = None,
    base_point: list[float] | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    target = os.path.abspath(os.path.expanduser(str(path)))
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    posix = target.replace("\\", "/")

    if block:
        lisp.evaluate(lisp.command("_.-WBLOCK", posix, str(block)), timeout=300)
        return {"written": target, "from_block": block}
    if not handles:
        raise AcadError("give handles to export, or a block name")
    lisp.evaluate(
        lisp.command(
            "_.-WBLOCK", posix, "", base_point or [0, 0, 0], lisp.ss_from(handles), ""
        ),
        timeout=300,
    )
    return {"written": target, "entities": len(handles)}


@tool(description="Work with external references: list, attach, detach, reload, unload or bind them.")
def xref(
    action: str = "list",
    path: str | None = None,
    name: str | None = None,
    position: list[float] | None = None,
    scale: float = 1.0,
    rotation: float = 0.0,
    overlay: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    verb = str(action).strip().lower()

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)

        if verb == "list":
            rows = []
            for i in range(int(doc.Blocks.Count)):
                block = doc.Blocks.Item(i)
                if not com.quiet(lambda: block.IsXRef, False):
                    continue
                rows.append(
                    {
                        "name": str(block.Name),
                        "path": str(com.quiet(lambda: block.Path, "") or ""),
                        "found": os.path.isfile(str(com.quiet(lambda: block.Path, "") or "")),
                    }
                )
            return {"count": len(rows), "xrefs": rows}

        if verb == "attach":
            if not path:
                raise AcadError("attaching an xref needs a path")
            full = os.path.abspath(os.path.expanduser(str(path)))
            if not os.path.isfile(full):
                raise AcadError(f"There is no file at {full}")
            label = str(name or os.path.splitext(os.path.basename(full))[0])
            ref = com.retry(
                lambda: doc.ModelSpace.AttachExternalReference(
                    full, label, com.pt(position or [0, 0, 0]),
                    float(scale), float(scale), float(scale),
                    math.radians(float(rotation)), bool(overlay),
                ),
                timeout=300,
            )
            return {"attached": label, "path": full, "handle": str(ref.Handle)}

        if not name:
            raise AcadError(f"{verb} needs the xref name")
        block = _find_block(doc, name)
        if verb == "detach":
            com.retry(lambda: block.Detach(), timeout=180)
            return {"detached": name}
        if verb == "reload":
            com.retry(lambda: block.Reload(), timeout=180)
            return {"reloaded": name}
        if verb == "unload":
            com.retry(lambda: block.Unload(), timeout=180)
            return {"unloaded": name}
        if verb == "bind":
            com.retry(lambda: block.Bind(False), timeout=300)
            return {"bound": name}
        raise AcadError(
            "action must be list, attach, detach, reload, unload or bind"
        )

    return com.run_com(work, timeout=360)
