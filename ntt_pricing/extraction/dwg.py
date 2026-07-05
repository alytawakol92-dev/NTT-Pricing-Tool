"""Convert AutoCAD ``.dwg`` files to ``.dxf`` so they can be parsed.

DWG is a proprietary binary format that :mod:`ezdxf` cannot read directly.
This helper shells out to whichever converter is installed:

* **LibreDWG** ``dwg2dxf`` (free, open source), or
* the **ODA File Converter** (free download from the Open Design Alliance).

If neither is available a clear, actionable error is raised telling the user
how to proceed (install a converter, or export the drawing to DXF from
AutoCAD).  The path to a converter can also be forced with the
``NTT_DWG2DXF`` environment variable.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile


def dwg_converter() -> str | None:
    """Return a usable dwg->dxf converter command, or None."""
    forced = os.environ.get("NTT_DWG2DXF")
    if forced and (os.path.isfile(forced) or shutil.which(forced)):
        return forced
    for cand in ("dwg2dxf", "ODAFileConverter"):
        if shutil.which(cand):
            return cand
    return None


def convert_dwg_to_dxf(dwg_path: str, out_dir: str | None = None) -> str:
    """Convert *dwg_path* to a DXF file and return the DXF path."""
    conv = dwg_converter()
    if conv is None:
        raise RuntimeError(
            "Cannot read DWG: no converter found. Install LibreDWG "
            "(provides 'dwg2dxf'), or the ODA File Converter, or export the "
            "drawing to DXF (R2010+) from AutoCAD. You can point the tool at a "
            "converter with the NTT_DWG2DXF environment variable.")

    out_dir = out_dir or tempfile.mkdtemp(prefix="ntt_dwg_")
    base = os.path.splitext(os.path.basename(dwg_path))[0]
    out_path = os.path.join(out_dir, base + ".dxf")

    name = os.path.basename(conv).lower()
    if "oda" in name:
        # ODAFileConverter <in_dir> <out_dir> <ver> <fmt> <recurse> <audit> <filter>
        subprocess.run([conv, os.path.dirname(os.path.abspath(dwg_path)), out_dir,
                        "ACAD2018", "DXF", "0", "1", os.path.basename(dwg_path)],
                       check=True, capture_output=True, timeout=120)
    else:
        # LibreDWG dwg2dxf -o out.dxf in.dwg
        subprocess.run([conv, "-o", out_path, dwg_path],
                       check=True, capture_output=True, timeout=120)

    if not os.path.exists(out_path):
        raise RuntimeError(f"DWG conversion produced no output ({conv}).")
    return out_path
