# -*- coding: utf-8 -*-
"""📦 Country pack import module.

Reverses country_pack.py: given a country pack GeoPackage (built by
build_country_pack()) and an empty working directory, reconstructs a
fully configured GeoE3 project there - study_area/study_area.gpkg,
every configured input the model points at, every already-computed
result, and model.json itself - ready to open as a project with no
further setup.

The pack's own PROJECT_MODEL_TABLE_NAME table is the starting point: it
is a verbatim copy of the exporting project's model.json, including
every indicator's original (now stale, pointing at the exporting
machine) source-field values. Those same values are what
indicator_source()/project_level_sources()/result_sources() used to
decide what to write into the pack and under what layer name - so
walking the model with the exact same field-mapping constants recovers,
for each layer name in the pack, which field on which node to overwrite
with a freshly-extracted local path. Every table name in the pack that
doesn't match one of those three categories (and isn't one of the two
fixed metadata tables) is assumed to be a study_area.gpkg layer,
bundled wholesale on export - see study_area_sources()'s docstring for
why that's a safe assumption today.

Styles embedded in the pack's layer_styles table (see country_pack.py's
_apply_style()) are intentionally not restored here - out of scope for
"the project is configured and ready to run."

Every function here does its own file I/O (GDAL/OGR) and never touches
QgsProject.instance() - safe to call from a QgsTask worker thread, same
as country_pack.py.
"""

import json
import os
from typing import Callable, Dict, List, Optional

from osgeo import gdal

from geest.core.country_pack import (
    INDEX_SCORE_TABLE_NAME,
    PROJECT_LEVEL_SOURCES,
    PROJECT_MODEL_TABLE_NAME,
    RESULT_SUFFIX,
    S2S_VECTOR_FIELD_BY_MODE,
    TOP_LEVEL_RESULT_RASTER_FIELDS,
    TOP_LEVEL_SUBNATIONAL_AGGREGATION_FIELDS,
    _indicator_source_field,
    _iter_result_nodes,
    _project_level_source_field,
)
from geest.utilities import log_message


def _all_table_names(pack_path: str) -> set:
    """Every table name a country pack GeoPackage contains, vector and raster alike.

    Args:
        pack_path: Path to the country pack GeoPackage.

    Returns:
        Every table name gpkg_contents lists, or an empty set if the
        file can't be opened at all.
    """
    dataset = gdal.OpenEx(pack_path, gdal.OF_ALL)
    if dataset is None:
        return set()
    names = set()
    result = dataset.ExecuteSQL("SELECT table_name FROM gpkg_contents")
    for feature in result:
        names.add(feature.GetField("table_name"))
    dataset.ReleaseResultSet(result)
    dataset = None
    return names


def _read_project_model(pack_path: str) -> dict:
    """Read the pack's PROJECT_MODEL_TABLE_NAME table back into a dict.

    Args:
        pack_path: Path to the country pack GeoPackage.

    Returns:
        The parsed model.json document the pack was built from.

    Raises:
        RuntimeError: If the pack can't be opened or has no
            PROJECT_MODEL_TABLE_NAME table (i.e. isn't a country pack,
            or predates this feature).
    """
    dataset = gdal.OpenEx(pack_path, gdal.OF_ALL)
    if dataset is None:
        raise RuntimeError(f"Could not open country pack '{pack_path}'")
    layer = dataset.GetLayerByName(PROJECT_MODEL_TABLE_NAME)
    if layer is None:
        dataset = None
        raise RuntimeError(
            f"'{pack_path}' has no {PROJECT_MODEL_TABLE_NAME} table - "
            "it isn't a country pack, or was built before this feature existed."
        )
    feature = layer.GetNextFeature()
    model = json.loads(feature.GetField("model_json"))
    dataset = None
    return model


def _indicator_import_targets(model: dict) -> Dict[str, tuple]:
    """layer_name -> (indicator, field_name, kind) for every indicator's configured input.

    Mirrors indicator_source()'s own traversal and field resolution (via
    _indicator_source_field()) so a layer name found in the pack maps
    back to the exact field that produced it.

    Args:
        model: The parsed model.json document.

    Returns:
        One entry per indicator that has a file-based input configured.
    """
    targets = {}
    for dimension in model.get("dimensions", []):
        for factor in dimension.get("factors", []):
            for indicator in factor.get("indicators", []):
                layer_name = indicator.get("id")
                if not layer_name:
                    continue
                resolved = _indicator_source_field(indicator)
                if resolved:
                    field_name, kind, _, _ = resolved
                    targets[layer_name] = (indicator, field_name, kind)
    return targets


def _project_level_import_targets(model: dict) -> Dict[str, tuple]:
    """layer_name -> (field_name, kind) for every project-level configured input.

    Args:
        model: The parsed model.json document.

    Returns:
        One entry per project-level input (road network, population,
        masks, aggregation boundary) that's actually configured.
    """
    targets = {}
    for layer_name, field_names, kind in PROJECT_LEVEL_SOURCES:
        field_name = _project_level_source_field(model, field_names)
        if not field_name:
            continue
        actual_kind = kind or ("raster" if model.get("population_source") == "raster" else "vector")
        targets[layer_name] = (field_name, actual_kind)
    return targets


def _result_import_targets(model: dict) -> Dict[str, tuple]:
    """layer_name -> (node, field_name, kind) for every already-computed result.

    Args:
        model: The parsed model.json document.

    Returns:
        One entry per indicator/factor/dimension/top-level node that has
        a result_file configured, keyed by result_sources()'s own
        "{name}_result" naming, plus one entry per configured extra
        top-level composite product (TOP_LEVEL_RESULT_RASTER_FIELDS/
        TOP_LEVEL_SUBNATIONAL_AGGREGATION_FIELDS), keyed by their own
        field name directly (see result_sources()'s docstring - these
        don't need dim_/fac_ prefixing, their names are already unique).
    """
    targets = {
        f"{name}{RESULT_SUFFIX}": (node, "result_file", "raster")
        for name, node in _iter_result_nodes(model)
        if node.get("result_file")
    }
    for field in TOP_LEVEL_RESULT_RASTER_FIELDS:
        if model.get(field):
            targets[field] = (model, field, "raster")
    for field in TOP_LEVEL_SUBNATIONAL_AGGREGATION_FIELDS:
        if model.get(field):
            targets[field] = (model, field, "vector")
    return targets


def _sync_s2s_output_path(indicator: dict) -> None:
    """Point a Space2Stats indicator's s2s_output_path at its new, already-rewritten layer_source file.

    s2s_output_path duplicates the SAME GeoPackage environmental_
    hazards_layer_source/nighttime_lights_layer_source references (just
    without the "|layername=" suffix) - confirmed on a real regional-
    scale project. Only the layer_source field is rewritten by the main
    import loop (it's the field indicator_source() actually reads);
    this keeps the duplicate in sync so it doesn't keep pointing at the
    exporting machine's path.

    Args:
        indicator: One (already-rewritten) indicator object from the
            reconstructed model.
    """
    if not indicator.get("s2s_output_path"):
        return
    for field_name in S2S_VECTOR_FIELD_BY_MODE.values():
        value = indicator.get(field_name)
        if value:
            indicator["s2s_output_path"] = value.split("|layername=")[0]
            return


def _extract_raster(pack_path: str, table_name: str, out_dir: str) -> str:
    """Pull one raster table out of the pack as a standalone GeoTIFF.

    Args:
        pack_path: Path to the country pack GeoPackage.
        table_name: Name of the raster table to extract.
        out_dir: Directory to write the GeoTIFF into (created if needed).

    Returns:
        Path to the written GeoTIFF.

    Raises:
        RuntimeError: If the translate fails.
    """
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{table_name}.tif")
    result = gdal.Translate(out_path, f"GPKG:{pack_path}:{table_name}", format="GTiff")
    if result is None:
        raise RuntimeError(f"Failed to extract raster '{table_name}': {gdal.GetLastErrorMsg()}")
    result = None  # noqa: F841 - closes/flushes the dataset
    return out_path


def _extract_csv(pack_path: str, table_name: str, out_dir: str) -> str:
    """Pull one vector table out of the pack as a standalone CSV.

    The one CSV-sourced indicator type (FCV/ACLED) keeps its "longitude"/
    "latitude" columns as plain attribute fields even once reprojected
    into the pack as a point layer (X_POSSIBLE_NAMES/Y_POSSIBLE_NAMES
    only affects geometry interpretation on read, not the source
    columns) - so translating straight back to CSV recovers them as
    ordinary columns, no special handling needed.

    Args:
        pack_path: Path to the country pack GeoPackage.
        table_name: Name of the vector table to extract.
        out_dir: Directory to write the CSV into (created if needed).

    Returns:
        Path to the written CSV.

    Raises:
        RuntimeError: If the translate fails.
    """
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{table_name}.csv")
    # pack_path on its own, with table_name as a trailing positional
    # selector - not "pack_path|layername=table_name" - see
    # _extract_vector_into()'s matching comment for why.
    options = gdal.VectorTranslateOptions(format="CSV", options=[table_name])
    result = gdal.VectorTranslate(out_path, pack_path, options=options)
    if result is None:
        raise RuntimeError(f"Failed to extract CSV '{table_name}': {gdal.GetLastErrorMsg()}")
    result = None  # noqa: F841 - closes/flushes the dataset
    return out_path


def _extract_vector_into(pack_path: str, table_name: str, out_gpkg: str) -> str:
    """Pull one vector table out of the pack and append it into a local GeoPackage.

    Args:
        pack_path: Path to the country pack GeoPackage.
        table_name: Name of the vector table to extract.
        out_gpkg: Path to the destination GeoPackage (created on first
            call, appended to thereafter).

    Returns:
        A "{out_gpkg}|layername={table_name}" URI for the new layer.

    Raises:
        RuntimeError: If the translate fails.
    """
    os.makedirs(os.path.dirname(out_gpkg), exist_ok=True)
    # Re-checked fresh on every call, not tracked across calls - see
    # build_country_pack()'s matching comment for the exact failure mode
    # ("append" meaning "have I written this KIND before" let a raster
    # write wipe an already-written vector layer) this avoids repeating.
    append = os.path.exists(out_gpkg)
    # pack_path on its own, with table_name as a trailing positional
    # selector in "options" - GDAL's Python API doesn't understand
    # QGIS's "path|layername=X" convention as a source string (see
    # country_pack.py's _split_source_uri() docstring: passed straight
    # through, it fails with "ERROR 1: hSrcDS == NULL"). This is the
    # same selector mechanism write_vector_source() already uses to
    # pick one layer out of a multi-layer source.
    options = gdal.VectorTranslateOptions(
        format="GPKG",
        layerName=table_name,
        accessMode="append" if append else None,
        options=[table_name],
    )
    result = gdal.VectorTranslate(out_gpkg, pack_path, options=options)
    if result is None:
        raise RuntimeError(f"Failed to extract vector '{table_name}': {gdal.GetLastErrorMsg()}")
    result = None  # noqa: F841 - closes/flushes the dataset
    return f"{out_gpkg}|layername={table_name}"


def import_country_pack(
    pack_path: str,
    working_directory: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, List[str]]:
    """Reconstruct a full GeoE3 project from a country pack GeoPackage.

    Args:
        pack_path: Path to the country pack GeoPackage to import.
        working_directory: An empty (no model.json yet) directory to
            reconstruct the project into.
        progress_callback: Optional callback(done_count, total_count,
            current_table_name), called after each table is processed.

    Returns:
        {"imported": [...], "skipped": [...]} - table names successfully
        extracted and wired into the reconstructed model.json, and names
        that failed to extract (logged, not fatal to the rest of the
        import - the same "one bad source shouldn't abort everything"
        policy as build_country_pack()).

    Raises:
        RuntimeError: If working_directory already has a model.json (to
            avoid clobbering an existing project), or pack_path isn't a
            country pack (no PROJECT_MODEL_TABLE_NAME table).
    """
    model_json_path = os.path.join(working_directory, "model.json")
    if os.path.exists(model_json_path):
        raise RuntimeError(f"'{working_directory}' already has a model.json - import needs an empty working directory.")

    model = _read_project_model(pack_path)
    indicator_targets = _indicator_import_targets(model)
    project_targets = _project_level_import_targets(model)
    result_targets = _result_import_targets(model)

    reserved = {INDEX_SCORE_TABLE_NAME, PROJECT_MODEL_TABLE_NAME}
    table_names = _all_table_names(pack_path) - reserved
    study_area_layer_names = table_names - set(indicator_targets) - set(project_targets) - set(result_targets)

    imports_dir = os.path.join(working_directory, "country_pack_imports")
    inputs_dir = os.path.join(imports_dir, "inputs")
    results_dir = os.path.join(imports_dir, "results")
    inputs_gpkg = os.path.join(imports_dir, "inputs.gpkg")
    results_gpkg = os.path.join(imports_dir, "results.gpkg")
    study_area_gpkg = os.path.join(working_directory, "study_area", "study_area.gpkg")

    imported: List[str] = []
    skipped: List[str] = []
    ordered_names = sorted(table_names)

    for index, table_name in enumerate(ordered_names):
        if progress_callback:
            progress_callback(index, len(ordered_names), table_name)
        try:
            if table_name in indicator_targets:
                node, field_name, kind = indicator_targets[table_name]
                if kind == "raster":
                    node[field_name] = _extract_raster(pack_path, table_name, inputs_dir)
                elif kind == "csv":
                    node[field_name] = _extract_csv(pack_path, table_name, inputs_dir)
                else:
                    node[field_name] = _extract_vector_into(pack_path, table_name, inputs_gpkg)
            elif table_name in project_targets:
                field_name, kind = project_targets[table_name]
                if kind == "raster":
                    model[field_name] = _extract_raster(pack_path, table_name, inputs_dir)
                else:
                    model[field_name] = _extract_vector_into(pack_path, table_name, inputs_gpkg)
            elif table_name in result_targets:
                node, field_name, kind = result_targets[table_name]
                if kind == "raster":
                    node[field_name] = _extract_raster(pack_path, table_name, results_dir)
                else:
                    node[field_name] = _extract_vector_into(pack_path, table_name, results_gpkg)
            elif table_name in study_area_layer_names:
                _extract_vector_into(pack_path, table_name, study_area_gpkg)
            else:
                continue
            imported.append(table_name)
        except Exception as e:
            # Broad on purpose, matching build_country_pack()'s own
            # policy: one bad table (corrupted, an unsupported pixel
            # type on this GDAL build, whatever) shouldn't abort
            # reconstructing everything else.
            log_message(f"Skipping '{table_name}' on import: {e}", tag="GeoE3")
            skipped.append(table_name)

    if progress_callback:
        progress_callback(len(ordered_names), len(ordered_names), "")

    # The model records its own working directory - stale after a move,
    # same as every other path rewritten above.
    if "working_folder" in model:
        model["working_folder"] = working_directory

    # qgis_project_path points at the exporting project's own .qgz,
    # whose layers reference the exporting machine's paths - unlike
    # every other field above, there's no local copy of it to rewrite
    # to, so it's cleared rather than left dangling. If it survived,
    # the dock's open_associated_qgis_project() would load that .qgz
    # wholesale the moment this import finishes, pulling layers
    # pointing outside the new working directory into what's supposed
    # to be a freshly started QGIS project.
    if "qgis_project_path" in model:
        model["qgis_project_path"] = ""

    for dimension in model.get("dimensions", []):
        for factor in dimension.get("factors", []):
            for indicator in factor.get("indicators", []):
                _sync_s2s_output_path(indicator)

    with open(model_json_path, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)

    return {"imported": imported, "skipped": skipped}
