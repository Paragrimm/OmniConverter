import numpy as np
import pytest
import trimesh
from PIL import Image

from omniconverter.core.errors import ConversionError
from omniconverter.core.formats import get_format
from tests.conftest import needs_blender

MESH_TARGETS = ("obj", "glb", "gltf", "stl", "ply")


@pytest.fixture
def model(tmp_path):
    """A 1 × 2 × 3 box (Y is the 2) with a red texture, saved as GLB."""
    box = trimesh.creation.box(extents=(1, 2, 3))
    uv = np.random.default_rng(1).random((len(box.vertices), 2))
    material = trimesh.visual.material.PBRMaterial(
        name="Owl Feathers", baseColorTexture=Image.new("RGB", (8, 8), (200, 40, 40)))
    box.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    path = tmp_path / "my box.glb"
    trimesh.Scene({"Box": box}).export(str(path))
    return path


def convert(converter, path, target, **options):
    source = converter.inspect(path)
    fmt = get_format(target)
    return converter.convert(source, fmt, converter.output_path(source, fmt), options)


def extents(path):
    return np.round(trimesh.load(str(path), force="scene").extents, 4).tolist()


@pytest.mark.parametrize("target", MESH_TARGETS)
def test_mesh_formats(converter, model, target):
    out = convert(converter, model, target)
    assert out.suffix == f".{target}"
    assert extents(out) == [1, 2, 3]
    back = convert(converter, out, "glb")
    assert extents(back) == [1, 2, 3]


def test_scale_and_up_axis(converter, model):
    assert extents(convert(converter, model, "stl", scale="m_to_mm")) == [1000, 2000, 3000]
    assert extents(convert(converter, model, "glb", up_axis="y_to_z")) == [1, 3, 2]
    assert extents(convert(converter, model, "ply", up_axis="z_to_y", scale="cm_to_m")) == [
        0.01, 0.03, 0.02]


def test_stl_as_text(converter, model):
    out = convert(converter, model, "stl", ascii=True)
    assert out.read_text().startswith("solid")


def test_obj_brings_material_and_texture_along(converter, model, tmp_path):
    out = convert(converter, model, "obj")
    assert out.name == "my box.obj"
    assert "mtllib my_box.mtl" in out.read_text()  # no spaces: OBJ splits on whitespace
    mtl = (tmp_path / "my_box.mtl").read_text()
    texture = next(line.split(maxsplit=1)[1] for line in mtl.splitlines()
                   if line.startswith("map_Kd"))
    assert texture.startswith("my_box_") and (tmp_path / texture).is_file()
    reloaded = trimesh.load(str(out), force="scene")
    visual = next(iter(reloaded.geometry.values())).visual
    assert visual.material.image is not None

    second = convert(converter, model, "obj")  # a second run gets its own companions
    assert second.name == "my box (1).obj"
    assert (tmp_path / "my_box_(1).mtl").is_file()


def test_obj_companions_never_overwrite(converter, model, tmp_path):
    (tmp_path / "my_box.mtl").write_text("mine")
    with pytest.raises(ConversionError, match="already exists"):
        convert(converter, model, "obj")
    assert (tmp_path / "my_box.mtl").read_text() == "mine"
    assert not (tmp_path / "my box.obj").exists()
    assert not [p for p in tmp_path.iterdir() if ".omni-" in p.name]


def test_broken_and_empty_files(converter, tmp_path):
    broken = tmp_path / "broken.glb"
    broken.write_bytes(b"glTF not really")
    with pytest.raises(ConversionError):
        convert(converter, broken, "obj")
    empty = tmp_path / "empty.obj"
    empty.write_text("# nothing here\n")
    with pytest.raises(ConversionError):
        convert(converter, empty, "stl")


def test_fbx_needs_blender(converter, model, monkeypatch):
    find = converter.locator.find
    monkeypatch.setattr(converter.locator, "find",
                        lambda tool: None if tool == "blender" else find(tool))
    choices = {c.format.id: c for c in converter.targets([converter.inspect(model)])}
    assert choices["obj"].available
    assert not choices["fbx"].available and choices["fbx"].missing_tools == ("blender",)


@needs_blender
def test_fbx_round_trip_with_blender(converter, model, tmp_path):
    fbx = convert(converter, model, "fbx")
    assert fbx.read_bytes().startswith(b"Kaydara FBX Binary")
    assert extents(convert(converter, fbx, "glb")) == [1, 2, 3]
    obj = convert(converter, fbx, "obj", scale="m_to_cm")  # FBX → GLB (Blender) → OBJ
    assert extents(obj) == [100, 200, 300]
    assert list(tmp_path.glob("my_box*.png"))  # the texture survived the trip through FBX
    stl_fbx = convert(converter, convert(converter, model, "stl"), "fbx", up_axis="y_to_z")
    assert extents(convert(converter, stl_fbx, "glb")) == [1, 3, 2]
    # Blender must not leave anything next to the source (e.g. unpacked textures)
    assert not [p for p in tmp_path.iterdir() if p.is_dir() or ".omni-" in p.name]
