"""3D models: OBJ, glTF/GLB, STL and PLY with trimesh; FBX through Blender."""

from __future__ import annotations

import math
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from omniconverter.core import process
from omniconverter.core.backend import Backend, Conversion, ConversionContext, ConversionRequest
from omniconverter.core.errors import ConversionError
from omniconverter.core.formats import Format
from omniconverter.core.options import Kind, Option
from omniconverter.core.probe import MediaInfo
from omniconverter.i18n import t

MESH_FORMATS = ("obj", "glb", "gltf", "stl", "ply")  # handled in-process by trimesh
BLENDER_INPUTS = ("fbx", "glb", "gltf")  # what Blender itself imports (keeps rigs/animation)

SCALES = {"none": 1.0, "cm_to_m": 0.01, "m_to_cm": 100.0, "mm_to_m": 0.001,
          "m_to_mm": 1000.0, "inch_to_mm": 25.4}
UP_AXES = ("keep", "y_to_z", "z_to_y")

_STEM_UNSAFE = re.compile(r"[\s\\/]+")  # OBJ's mtllib/map_Kd lines split on whitespace


def model_options(target: Format) -> list[Option]:
    opts = [
        Option("scale", t("opt.model_scale"), Kind.CHOICE, "none",
               choices=tuple((k, t(f"opt.model_scale.{k}")) for k in SCALES),
               help=t("opt.model_scale_help")),
        Option("up_axis", t("opt.model_up_axis"), Kind.CHOICE, "keep",
               choices=tuple((k, t(f"opt.model_up_axis.{k}")) for k in UP_AXES),
               help=t("opt.model_up_axis_help")),
    ]
    if target.id in ("stl", "ply"):
        opts.append(Option("ascii", t("opt.model_ascii"), Kind.BOOL, False, advanced=True))
    return opts


def transform_matrix(opts: dict[str, Any]) -> Any | None:
    """Scale and up-axis change as 4×4 matrix, or ``None`` if nothing changes."""
    import numpy as np

    factor = SCALES.get(opts.get("scale", "none"), 1.0)
    axis = opts.get("up_axis", "keep")
    if factor == 1.0 and axis == "keep":
        return None
    matrix = np.diag([factor, factor, factor, 1.0])
    if axis != "keep":
        angle = math.pi / 2 if axis == "y_to_z" else -math.pi / 2  # rotation about X
        c, s = round(math.cos(angle)), round(math.sin(angle))
        rotation = np.array([[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]], float)
        matrix = matrix @ rotation
    return matrix


def load_scene(path: Path, fmt: str) -> Any:
    """Load a model as ``trimesh.Scene``; only files next to it are read (no network)."""
    import trimesh
    from trimesh.resolvers import FilePathResolver

    try:
        with path.open("rb") as handle:
            scene = trimesh.load(handle, file_type=fmt, force="scene",
                                 resolver=FilePathResolver(str(path)))
    except ConversionError:
        raise
    except Exception as exc:  # trimesh raises all kinds of errors for broken files
        raise ConversionError(t("error.model_failed"), f"{type(exc).__name__}: {exc}") from exc
    if not scene.geometry:
        raise ConversionError(t("error.model_empty"))
    return scene


def export_scene(scene: Any, output: Path, target: str, opts: dict[str, Any],
                 ctx: ConversionContext) -> None:
    from trimesh.exchange import gltf, ply, stl

    try:
        if target == "glb":
            data: bytes | str = scene.export(file_type="glb")
        elif target == "gltf":
            files = gltf.export_gltf(scene, embed_buffers=True)  # one self-contained file
            data = next(v for k, v in files.items() if k.endswith(".gltf"))
        elif target in ("stl", "ply"):
            mesh = scene.to_mesh()
            if len(mesh.faces) == 0:
                raise ConversionError(t("error.model_empty"))
            ascii_ = bool(opts.get("ascii"))
            if target == "stl":
                data = stl.export_stl_ascii(mesh) if ascii_ else stl.export_stl(mesh)
            else:
                data = ply.export_ply(mesh, encoding="ascii" if ascii_ else "binary")
        else:
            data = _export_obj(scene, output, ctx)
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError(t("error.model_failed"), f"{type(exc).__name__}: {exc}") from exc
    output.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def _export_obj(scene: Any, output: Path, ctx: ConversionContext) -> str:
    """OBJ text; its .mtl and textures become companion files named after the result."""
    from trimesh.exchange import obj

    final = ctx.final_path or output
    stem = _STEM_UNSAFE.sub("_", final.stem) or "model"
    mtl_name = f"{stem}.mtl"
    text, files = obj.export_obj(scene, include_texture=True, return_texture=True,
                                 mtl_name=mtl_name)
    mtl = files.pop(mtl_name, None)
    renamed = {name: f"{stem}_{_STEM_UNSAFE.sub('_', name)}" for name in files}
    if mtl is not None:
        lines = mtl.decode("utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            for old, new in renamed.items():
                if line.startswith(("map_", "bump", "disp", "decal", "norm")) and \
                        line.endswith(old):
                    lines[i] = line[: -len(old)] + new
        ctx.companions[mtl_name] = ("\n".join(lines) + "\n").encode("utf-8")
    for old, data in files.items():
        ctx.companions[renamed[old]] = data
    return text


class MeshBackend(Backend):
    """OBJ, GLB, glTF, STL and PLY among each other, without external programs."""

    id = "trimesh"

    def conversions(self) -> Iterable[Conversion]:
        for src in MESH_FORMATS:
            for dst in MESH_FORMATS:
                yield Conversion(src, dst)

    def options(self, source: Format, target: Format, media: MediaInfo | None = None
                ) -> list[Option]:
        return model_options(target)

    def convert(self, request: ConversionRequest, output: Path, ctx: ConversionContext) -> None:
        ctx.progress(None)
        assert request.source is not None
        scene = load_scene(request.source, request.source_format.id)
        ctx.check_cancelled()
        matrix = transform_matrix(request.options)
        if matrix is not None:
            scene.apply_transform(matrix)
        export_scene(scene, output, request.target_format.id, request.options, ctx)


# Runs inside Blender: import, optionally transform, export. Arguments follow "--".
_BLENDER_SCRIPT = r"""
import sys
import bpy
import mathutils

src, dst, matrix = sys.argv[sys.argv.index("--") + 1:][:3]
bpy.ops.wm.read_factory_settings(use_empty=True)
ext = src.rsplit(".", 1)[-1].lower()
if ext == "fbx":
    bpy.ops.import_scene.fbx(filepath=src)
else:
    bpy.ops.import_scene.gltf(filepath=src)
if not bpy.context.scene.objects:
    raise RuntimeError("the file contains no objects")
if matrix != "-":
    values = [float(v) for v in matrix.split(",")]
    m = mathutils.Matrix([values[0:4], values[4:8], values[8:12], values[12:16]])
    # Parent everything to one transformed empty, so animations keep working.
    root = bpy.data.objects.new("root", None)
    bpy.context.scene.collection.objects.link(root)
    for obj in list(bpy.context.scene.objects):
        if obj.parent is None and obj is not root:
            obj.parent = root
    root.matrix_world = m
if dst.lower().endswith(".fbx"):
    bpy.ops.export_scene.fbx(filepath=dst, path_mode="COPY", embed_textures=True)
else:
    bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB")
"""


def _matrix_arg(matrix: Any | None) -> str:
    if matrix is None:
        return "-"
    return ",".join(f"{v:.10g}" for v in matrix.flatten())


def run_blender(ctx: ConversionContext, source: Path, output: Path, matrix: Any | None) -> None:
    blender = ctx.locator.require("blender")
    profile = ctx.work_dir / "blender-profile"  # private settings, no history left behind
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    for var, sub in (("BLENDER_USER_RESOURCES", ""), ("BLENDER_USER_CONFIG", "config"),
                     ("BLENDER_USER_SCRIPTS", "scripts"), ("BLENDER_USER_DATAFILES", "data")):
        env[var] = str(profile / sub)
    args = [blender, "--background", "--factory-startup", "-noaudio",
            "--python-exit-code", "1", "--python-expr", _BLENDER_SCRIPT,
            "--", str(source), str(output), _matrix_arg(matrix)]
    result = process.run(args, cancel=ctx.cancel, cwd=ctx.work_dir, env=env, check=False)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        stdout = "\n".join(result.stdout.splitlines()[-40:])
        raise ConversionError(t("error.blender_failed"),
                              f"{stdout}\n{result.stderr_tail}".strip())


class BlenderBackend(Backend):
    """Everything with FBX. Blender converts FBX ↔ GLB, trimesh does the rest."""

    id = "blender"
    _REQUIRES = ("blender",)

    def conversions(self) -> Iterable[Conversion]:
        for fmt in (*MESH_FORMATS, "fbx"):
            yield Conversion("fbx", fmt, self._REQUIRES)
            if fmt != "fbx":
                yield Conversion(fmt, "fbx", self._REQUIRES)

    def options(self, source: Format, target: Format, media: MediaInfo | None = None
                ) -> list[Option]:
        return model_options(target)

    def convert(self, request: ConversionRequest, output: Path, ctx: ConversionContext) -> None:
        ctx.progress(None)
        assert request.source is not None
        src, dst = request.source_format.id, request.target_format.id
        matrix = transform_matrix(request.options)
        if src in BLENDER_INPUTS and dst in ("fbx", "glb"):
            run_blender(ctx, request.source, output, matrix)
            return
        intermediate = ctx.work_dir / "intermediate.glb"
        if src == "fbx":  # FBX → GLB (Blender) → target (trimesh)
            run_blender(ctx, request.source, intermediate, matrix)
            ctx.check_cancelled()
            scene = load_scene(intermediate, "glb")
            export_scene(scene, output, dst, request.options, ctx)
        else:  # OBJ/STL/PLY → GLB (trimesh) → FBX (Blender)
            scene = load_scene(request.source, src)
            if matrix is not None:
                scene.apply_transform(matrix)
            export_scene(scene, intermediate, "glb", request.options, ctx)
            ctx.check_cancelled()
            run_blender(ctx, intermediate, output, None)
