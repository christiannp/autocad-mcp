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


@tool(undo_group=False, description="Write entities (or a whole block) out to a separate .dwg file - the WBLOCK command.")
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
            def scan() -> list[dict[str, Any]]:
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
                return rows

            # straight after WBLOCK or a block edit AutoCAD is briefly busy
            rows = com.retry(scan, timeout=30, attr_is_busy=True, context="listing xrefs")
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


def _inserts_named(doc: Any, block: str) -> list[Any]:
    """Block references whose effective name matches (dynamic blocks insert as *U names)."""
    target = str(block).lower()
    out = []
    for space in (doc.ModelSpace, doc.PaperSpace):
        for i in range(int(space.Count)):
            ent = space.Item(i)
            if util.dxf_type(ent) != "INSERT":
                continue
            name = str(com.quiet(lambda: ent.EffectiveName, "") or com.quiet(lambda: ent.Name, "") or "")
            if fnmatch.fnmatchcase(name.lower(), target):
                out.append(ent)
    return out


@tool(description=(
    "Dynamic block properties: read the parameters of block references "
    "(visibility state, distances, flips, lookups...) with their allowed "
    "values, set them with set_values {property: value}, or reset the block "
    "to its defaults. Give handles, or a block name to find every insert of "
    "it (the effective name works for dynamic blocks)."
))
def block_dynamic(
    handles: list[str] | None = None,
    block: str | None = None,
    set_values: dict[str, Any] | None = None,
    reset: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    if not handles and not block:
        raise AcadError("give handles, or a block name")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        refs = com.by_handles(doc, [str(h) for h in handles]) if handles else _inserts_named(doc, str(block))
        rows = []
        updated = 0
        for ref in refs:
            if util.dxf_type(ref) != "INSERT":
                continue
            dynamic = bool(com.quiet(lambda: ref.IsDynamicBlock, False))
            row: dict[str, Any] = {
                "handle": str(ref.Handle),
                "block": str(com.quiet(lambda: ref.EffectiveName, "") or com.quiet(lambda: ref.Name, "")),
                "dynamic": dynamic,
            }
            if dynamic:
                if reset:
                    com.quiet(lambda: ref.ResetBlock())
                props = list(com.unwrap(com.quiet(lambda: ref.GetDynamicBlockProperties(), []) or []))
                wanted = {str(k).lower(): v for k, v in (set_values or {}).items()}
                changed = []
                out_props = []
                for p in props:
                    pname = str(p.PropertyName)
                    if pname.lower() in wanted and not bool(com.quiet(lambda: p.ReadOnly, False)):
                        value = wanted[pname.lower()]
                        current = com.unwrap(p.Value)
                        if isinstance(current, (int, float)) and not isinstance(current, bool):
                            value = float(value)
                        p.Value = value
                        changed.append(pname)
                    allowed = com.unwrap(com.quiet(lambda: p.AllowedValues, []) or [])
                    out_props.append({
                        "name": pname,
                        "value": com.unwrap(p.Value),
                        "allowed": allowed if allowed else None,
                        "read_only": bool(com.quiet(lambda: p.ReadOnly, False)),
                        "description": str(com.quiet(lambda: p.Description, "") or "") or None,
                    })
                row["properties"] = [{k: v for k, v in o.items() if v is not None} for o in out_props]
                if changed:
                    row["changed"] = changed
                    updated += 1
                    com.quiet(lambda: ref.Update())
            rows.append(row)
        out: dict[str, Any] = {"count": len(rows), "inserts": rows}
        if set_values:
            out["updated"] = updated
        if reset:
            out["reset"] = True
        return out

    return com.run_com(work, timeout=300)


@tool(description=(
    "Push a block definition's attribute changes out to every insert of it "
    "(ATTSYNC) - needed after redefining a block whose attributes changed."
))
def attribute_sync(block: str, drawing: str | None = None) -> dict[str, Any]:
    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
    lisp.run_command("_.ATTSYNC", "_Name", str(block), doc=doc, timeout=300)
    return {"synchronised": block}


UNDERLAY_TYPES = {"IMAGE": "image", "PDFUNDERLAY": "pdf", "DWFUNDERLAY": "dwf", "DGNUNDERLAY": "dgn"}


def _underlay_row(ent: Any) -> dict[str, Any]:
    q = com.quiet
    kind = util.dxf_type(ent)
    row: dict[str, Any] = {
        "handle": str(ent.Handle),
        "kind": UNDERLAY_TYPES.get(kind, kind.lower()),
        "layer": str(q(lambda: ent.Layer, "")),
    }
    if kind == "IMAGE":
        row.update({
            "file": q(lambda: str(ent.ImageFile)),
            "name": q(lambda: str(ent.Name)),
            "origin": q(lambda: util.round_pt(ent.Origin)),
            "width": q(lambda: round(float(ent.ImageWidth), 4)),
            "height": q(lambda: round(float(ent.ImageHeight), 4)),
            "rotation": q(lambda: round(math.degrees(float(ent.Rotation)), 4)),
            "fade": q(lambda: int(ent.Fade)),
            "contrast": q(lambda: int(ent.Contrast)),
            "brightness": q(lambda: int(ent.Brightness)),
            "clipped": q(lambda: bool(ent.ClippingEnabled)),
        })
    else:
        row.update({
            "file": q(lambda: str(ent.File)),
            "name": q(lambda: str(ent.UnderlayName)),
            "page": q(lambda: str(ent.ItemName)),
            "position": q(lambda: util.round_pt(ent.Position)),
            "scale": q(lambda: round(float(ent.ScaleFactor), 6)),
            "rotation": q(lambda: round(math.degrees(float(ent.Rotation)), 4)),
            "fade": q(lambda: int(ent.Fade)),
            "contrast": q(lambda: int(ent.Contrast)),
            "monochrome": q(lambda: bool(ent.Monochrome)),
            "clipped": q(lambda: bool(ent.ClippingEnabled)),
        })
    row["bounds"] = util.bbox(ent)
    return {k: v for k, v in row.items() if v is not None}


@tool(description=(
    "Raster images and PDF underlays - a satellite photo of the roof, a scanned "
    "plan, a PDF drawing to trace over. action attach (kind image or pdf; "
    "give path, position, and either scale or the width the picture should "
    "have in drawing units), list, adjust (fade / contrast / brightness for "
    "the given handles, so an underlay sits quietly behind the drawing), "
    "detach (remove the given handles and their definitions), or frames "
    "(0 hide, 1 show, 2 show but do not plot)."
))
def underlay(
    action: str = "list",
    kind: str = "image",
    path: str | None = None,
    position: list[float] | None = None,
    scale: float = 1.0,
    width: float | None = None,
    rotation: float = 0.0,
    page: int = 1,
    handles: list[str] | None = None,
    fade: int | None = None,
    contrast: int | None = None,
    brightness: int | None = None,
    monochrome: bool | None = None,
    frames: int | None = None,
    layer: str | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    verb = str(action).strip().lower()
    what = str(kind).strip().lower()

    if verb == "list":
        found = lisp.evaluate(
            lisp.raw('(acadmcp:handles (ssget "_X" (list (cons 0 "IMAGE,PDFUNDERLAY,DWFUNDERLAY,DGNUNDERLAY"))))'),
            timeout=120,
        ) or []

        def rows() -> list[dict[str, Any]]:
            doc = com.find_doc(drawing)
            return [_underlay_row(com.by_handle(doc, str(h))) for h in found if h]

        out = com.run_com(rows, timeout=180) if found else []
        return {"count": len(out), "underlays": out}

    if verb == "frames":
        if frames is None:
            raise AcadError("frames needs a value: 0, 1 or 2")
        for var in ("IMAGEFRAME", "PDFFRAME", "DWFFRAME", "DGNFRAME"):
            lisp.evaluate(lisp.raw(f'(vl-catch-all-apply (quote setvar) (list "{var}" {int(frames)}))'), timeout=60)
        return {"frames": int(frames)}

    if verb == "attach":
        if not path or position is None:
            raise AcadError("attach needs path and position")
        full = os.path.abspath(os.path.expanduser(str(path)))
        if not os.path.isfile(full):
            raise AcadError(f"There is no file at {full}")
        if what == "image":
            def work() -> dict[str, Any]:
                doc = com.find_doc(drawing)
                if layer:
                    util.ensure_layer(doc, layer)
                ent = com.retry(
                    lambda: doc.ModelSpace.AddRaster(full, com.pt(position), float(scale), math.radians(float(rotation))),
                    timeout=180, context="attaching the image",
                )
                ent = com.by_handle(doc, str(ent.Handle))
                if width:
                    current = float(ent.ImageWidth)
                    if current > 0:
                        ent.ScaleEntity(com.pt(position), float(width) / current)
                if layer:
                    ent.Layer = str(layer)
                if fade is not None:
                    ent.Fade = int(fade)
                return _underlay_row(ent)

            return com.run_com(work, timeout=240)
        if what == "pdf":
            doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
            _, created = lisp.capture(
                lisp.command("_.-PDFATTACH", full, int(page), position, float(scale), float(rotation)),
                doc=doc, timeout=180,
            )
            if not created:
                raise AcadError("AutoCAD did not attach the PDF - check the page number and the file")
            if width or layer or fade is not None:
                def fix() -> dict[str, Any]:
                    d = com.find_doc(drawing)
                    ent = com.by_handle(d, created[-1])
                    if width:
                        box = util.bbox(ent)
                        if box and box["size"][0] > 0:
                            ent.ScaleEntity(com.pt(position), float(width) / box["size"][0])
                    if layer:
                        util.ensure_layer(d, layer)
                        ent.Layer = str(layer)
                    if fade is not None:
                        ent.Fade = int(fade)
                    return _underlay_row(ent)

                return com.run_com(fix, timeout=120)
            return {"created": created, "kind": "pdf", "file": full, "page": int(page)}
        raise AcadError("kind must be image or pdf (DWF/DGN: use cad_command with -DWFATTACH / -DGNATTACH)")

    if verb == "adjust":
        if not handles:
            raise AcadError("adjust needs handles")

        def adjust() -> dict[str, Any]:
            doc = com.find_doc(drawing)
            rows = []
            for h in handles:
                ent = com.by_handle(doc, str(h))
                if fade is not None:
                    ent.Fade = int(fade)
                if contrast is not None:
                    ent.Contrast = int(contrast)
                if brightness is not None and util.dxf_type(ent) == "IMAGE":
                    ent.Brightness = int(brightness)
                if monochrome is not None and util.dxf_type(ent) != "IMAGE":
                    ent.Monochrome = bool(monochrome)
                if layer:
                    util.ensure_layer(doc, layer)
                    ent.Layer = str(layer)
                rows.append(_underlay_row(ent))
            return {"count": len(rows), "underlays": rows}

        return com.run_com(adjust, timeout=180)

    if verb == "detach":
        if not handles:
            raise AcadError("detach needs handles")
        names: list[tuple[str, str]] = []

        def erase() -> None:
            doc = com.find_doc(drawing)
            for h in handles:
                ent = com.by_handle(doc, str(h))
                kind_ = util.dxf_type(ent)
                nm = str(com.quiet(lambda: ent.Name if kind_ == "IMAGE" else ent.UnderlayName, "") or "")
                names.append((kind_, nm))
                com.retry(lambda e=ent: e.Delete())

        com.run_com(erase, timeout=180)
        for kind_, nm in names:
            if kind_ == "IMAGE" and nm:
                com.quiet(lambda nm=nm: lisp.run_command("_.-IMAGE", "_Detach", nm, timeout=60))
        lisp.run_command("_.-PURGE", "_All", "*", "_No", timeout=120)
        return {"detached": len(handles)}

    raise AcadError("action must be list, attach, adjust, detach or frames")


@tool(description=(
    "Import the vector geometry of a PDF page as AutoCAD lines, arcs, text and "
    "hatches (PDFIMPORT) - from a file, or from a PDF underlay already in the "
    "drawing (give its handle). layers: 'pdf' keeps the PDF's own layers, "
    "'object' puts each object type on its own layer, 'current' uses the "
    "current layer. Returns the handles created."
))
def pdf_import(
    path: str | None = None,
    handle: str | None = None,
    page: int = 1,
    position: list[float] | None = None,
    scale: float = 1.0,
    rotation: float = 0.0,
    layers: str = "pdf",
    include_raster_images: bool = True,
    include_text: bool = True,
    include_solid_fills: bool = True,
    keep_underlay: bool = True,
    drawing: str | None = None,
) -> dict[str, Any]:
    if not path and not handle:
        raise AcadError("give a PDF path or the handle of a PDF underlay")
    layer_mode = {"pdf": 0, "object": 1, "current": 2}.get(str(layers).strip().lower())
    if layer_mode is None:
        raise AcadError("layers must be pdf, object or current")
    flt = 1 | (2 if include_solid_fills else 0) | (4 if include_text else 0) | (8 if include_raster_images else 0)
    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
    if path:
        full = os.path.abspath(os.path.expanduser(str(path)))
        if not os.path.isfile(full):
            raise AcadError(f"There is no file at {full}")
        body = lisp.command(
            "_.-PDFIMPORT", "_File", full, int(page), position or [0, 0], float(scale), float(rotation)
        )
    else:
        body = lisp.command(
            "_.-PDFIMPORT", lisp.entity(str(handle)), "_All", "_Keep" if keep_underlay else "_Detach"
        )
    _, created = lisp.capture(
        lisp.pushed({"PDFIMPORTLAYERS": layer_mode, "PDFIMPORTFILTER": flt}, body),
        doc=doc, timeout=600,
    )
    summary: dict[str, Any] = {"created": created[:500], "count": len(created)}
    if len(created) > 500:
        summary["note"] = f"{len(created)} entities were created; showing the first 500 handles"
    if created:
        counts = lisp.evaluate(
            lisp.raw(
                "(progn (setq amx-c nil) (foreach amx-h (list "
                + " ".join(lisp.lstr(h) for h in created[:500])
                + ") (setq amx-e (handent amx-h)) (if amx-e (progn (setq amx-t (cdr (assoc 0 (entget amx-e)))) "
                "(setq amx-a (assoc amx-t amx-c)) (if amx-a (setq amx-c (subst (cons amx-t (1+ (cdr amx-a))) amx-a amx-c)) "
                "(setq amx-c (cons (cons amx-t 1) amx-c)))))) amx-c)"
            ),
            doc=doc, timeout=120,
        ) or []
        summary["by_type"] = {str(k): v for k, v in counts if isinstance(k, str)} if counts else {}
    return summary
