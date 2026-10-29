# -*- coding: utf-8 -*-
"""📦 Country pack module.

Builds a single "country pack" GeoPackage from a project's own configured
INPUT data - not the computed indicator results, but the raw datasets a
user pointed each indicator at (the schools shapefile, the hazard raster,
the road network, and so on). Each one is clipped to the study area and
written as its own layer/raster table, named after the indicator's own
id for per-indicator sources, or a fixed name for project-level ones
(road network, population, masks, the subnational aggregation boundary).

Every function here does its own file I/O (GDAL/OGR) and never touches
QgsProject.instance() - safe to call from a QgsTask worker thread. If a
source is currently loaded in the user's live QGIS session and you want
its real styling embedded (rather than QGIS's default rendering),
resolve that style's XML on the MAIN THREAD first (reading the project's
layer registry off-thread is the same hazard class that corrupted
AnalysisReportTask - see base_report.py's history) and pass it in via
style_xml_by_path.
"""

import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from osgeo import gdal
from qgis.core import QgsRasterLayer, QgsVectorLayer
from qgis.PyQt.QtXml import QDomDocument

from geest.utilities import log_message

# analysis_mode -> indicator uses the generic VectorDataSourceWidget
# convention: "{mode without 'use_'}_layer_source" (picked from an
# already-open layer) or "..._shapefile" (browsed file) - whichever is
# populated. use_polygon_per_cell is here too: at regional scale it's
# actually Space2Stats-backed with no local file, which indicator_source()
# handles naturally by finding neither field populated.
VECTOR_WIDGET_MODES = {
    "use_multi_buffer_point",
    "use_single_buffer_point",
    "use_point_per_cell",
    "use_polyline_per_cell",
    "use_osm_transport_polyline_per_cell",
    "use_street_lights",
    "use_polygon_per_cell",
    "use_classify_polygon_into_classes",
    "use_classify_safety_polygon_into_classes",
}

#: analysis_mode -> the one field holding its raster path directly.
RASTER_FIELD_BY_MODE = {
    "use_environmental_hazards": "environmental_hazards_raster",
    "use_nighttime_lights": "nighttime_lights_raster",
}

#: analysis_mode -> (csv field name, x field, y field) for the one
#: CSV-sourced indicator type (FCV, backed by ACLED data), using ACLED's
#: own column names.
CSV_MODE_FIELDS = {
    "use_csv_to_point_layer": ("csv_to_point_layer_csv_file", "longitude", "latitude"),
}

#: Project-level (not per-indicator) inputs: output layer name -> candidate
#: field names to try in order -> data kind, or None when the kind varies
#: (population can be either, see population_source below).
PROJECT_LEVEL_SOURCES = [
    ("road_network", ["road_network_layer_path"], "vector"),
    ("population", ["population_layer_source", "population_shapefile"], None),
    ("point_mask", ["point_mask_layer_source", "point_mask_shapefile"], "vector"),
    ("polygon_mask", ["polygon_mask_layer_source", "polygon_mask_shapefile"], "vector"),
    ("raster_mask", ["raster_mask_layer_source", "raster_mask_raster"], "raster"),
    ("aggregation_boundary", ["aggregation_layer_source", "aggregation_shapefile"], "vector"),
]

#: GPKG's raster driver only supports these pixel types - anything else
#: must be downcast (see _raster_needs_float32()).
GPKG_RASTER_TYPES = ("Byte", "Int16", "UInt16", "Float32")


@dataclass
class PackSource:
    """One input dataset to copy into the country pack.

    Attributes:
        layer_name: Output layer/raster-table name in the pack.
        path: Path to the source dataset (may include a "|layername=..."
            suffix for a layer inside a GeoPackage).
        kind: "vector", "raster", or "csv".
        x_field: For kind "csv", the longitude/X column name.
        y_field: For kind "csv", the latitude/Y column name.
    """

    layer_name: str
    path: str
    kind: str
    x_field: Optional[str] = None
    y_field: Optional[str] = None


def indicator_source(indicator: dict) -> Optional[PackSource]:
    """The configured input dataset for one indicator.

    Args:
        indicator: One indicator object from model.json.

    Returns:
        A PackSource, or None if this indicator has no file-based input
        (a manually-typed national score such as EPLEX or a WBL factor,
        an indicator nobody has configured yet, or a regional-scale
        Space2Stats-backed polygon indicator with no local file).
    """
    mode = indicator.get("analysis_mode")
    layer_name = indicator.get("id")
    if not mode or not layer_name:
        return None

    if mode in RASTER_FIELD_BY_MODE:
        path = indicator.get(RASTER_FIELD_BY_MODE[mode])
        return PackSource(layer_name, path, "raster") if path else None

    if mode in CSV_MODE_FIELDS:
        field_name, x_field, y_field = CSV_MODE_FIELDS[mode]
        path = indicator.get(field_name)
        return PackSource(layer_name, path, "csv", x_field, y_field) if path else None

    if mode in VECTOR_WIDGET_MODES:
        widget_key = mode[len("use_") :]
        path = indicator.get(f"{widget_key}_layer_source") or indicator.get(f"{widget_key}_shapefile")
        return PackSource(layer_name, path, "vector") if path else None

    return None


def project_level_sources(model: dict) -> List[PackSource]:
    """The project-wide (not per-indicator) configured inputs.

    Args:
        model: The parsed model.json document.

    Returns:
        A PackSource for each project-level input that has actually been
        configured (empty/unset ones are omitted).
    """
    sources = []
    for layer_name, field_names, kind in PROJECT_LEVEL_SOURCES:
        path = None
        for field_name in field_names:
            path = model.get(field_name)
            if path:
                break
        if not path:
            continue
        actual_kind = kind
        if actual_kind is None:
            # Population is the one source whose kind varies project to
            # project - population_source records which it is.
            actual_kind = "raster" if model.get("population_source") == "raster" else "vector"
        sources.append(PackSource(layer_name, path, actual_kind))
    return sources


def all_sources(model: dict) -> List[PackSource]:
    """Every input dataset (indicator-level and project-level) this project has configured.

    Args:
        model: The parsed model.json document.

    Returns:
        One PackSource per configured input. Layer names are not
        deduplicated - several indicators can legitimately share the same
        underlying source file and each still gets its own named layer
        in the pack.
    """
    sources = list(project_level_sources(model))
    for dimension in model.get("dimensions", []):
        for factor in dimension.get("factors", []):
            for indicator in factor.get("indicators", []):
                source = indicator_source(indicator)
                if source:
                    sources.append(source)
    return sources


def _split_source_uri(path: str):
    """Split a "file|layername=X" QGIS-style URI into (base_path, layer_name).

    This "|layername=" convention is how QGIS points at one layer inside
    a multi-layer source (a GeoPackage, typically), but GDAL's own Python
    API doesn't understand it - passed straight through, GDAL just fails
    to open the literal (unsplit) string ("ERROR 1: hSrcDS == NULL").

    Args:
        path: A plain path, or "path|layername=name".

    Returns:
        (base_path, layer_name) - layer_name is None when the input had
        no "|layername=" suffix.
    """
    base_path, _, suffix = path.partition("|")
    if suffix.startswith("layername="):
        return base_path, suffix[len("layername=") :]
    return base_path, None


def _raster_needs_float32(path: str) -> bool:
    """Whether a raster's pixel type needs downcasting for GPKG storage.

    Args:
        path: Path to the source raster.

    Returns:
        True if the raster's data type isn't one GPKG's raster driver
        accepts (Byte/Int16/UInt16/Float32), False otherwise (including
        when the raster can't be opened - the warp itself will raise a
        clearer error in that case).
    """
    base_path, _ = _split_source_uri(path)
    dataset = gdal.Open(base_path)
    if dataset is None:
        return False
    dtype = gdal.GetDataTypeName(dataset.GetRasterBand(1).DataType)
    dataset = None
    return dtype not in GPKG_RASTER_TYPES


def write_raster_source(
    source: PackSource,
    study_area_gpkg: str,
    study_area_layer: str,
    out_gpkg: str,
    append: bool,
) -> None:
    """Clip a raster to the study area and write it into the pack as its own raster table.

    Args:
        source: The raster input to write.
        study_area_gpkg: Path to the study area GeoPackage.
        study_area_layer: Name of the study area polygon layer to clip against.
        out_gpkg: Path to the output country pack GeoPackage.
        append: True if out_gpkg already has at least one raster table
            (GDAL's GPKG driver needs APPEND_SUBDATASET=YES from the
            second raster onward, in the same file).

    Raises:
        RuntimeError: If the warp fails.
    """
    base_path, _ = _split_source_uri(source.path)
    if not os.path.exists(base_path):
        raise RuntimeError(f"Source file not found: {base_path}")
    creation_options = [f"RASTER_TABLE={source.layer_name}"]
    if append:
        creation_options.append("APPEND_SUBDATASET=YES")
    options = gdal.WarpOptions(
        format="GPKG",
        cutlineDSName=study_area_gpkg,
        cutlineLayer=study_area_layer,
        cropToCutline=True,
        outputType=(gdal.GDT_Float32 if _raster_needs_float32(source.path) else gdal.GDT_Unknown),
        creationOptions=creation_options,
    )
    result = gdal.Warp(out_gpkg, base_path, options=options)
    if result is None:
        raise RuntimeError(f"Failed to write raster '{source.layer_name}': {gdal.GetLastErrorMsg()}")
    result = None  # noqa: F841 - closes/flushes the dataset


def write_vector_source(
    source: PackSource,
    study_area_gpkg: str,
    study_area_layer: str,
    out_gpkg: str,
    append: bool,
) -> None:
    """Clip a vector layer to the study area and write it into the pack as its own layer.

    Args:
        source: The vector (or CSV-derived point) input to write.
        study_area_gpkg: Path to the study area GeoPackage.
        study_area_layer: Name of the study area polygon layer to clip against.
        out_gpkg: Path to the output country pack GeoPackage.
        append: True if out_gpkg already exists (GDAL's GPKG driver needs
            accessMode="append" to add a layer to an existing file rather
            than overwriting it).

    Raises:
        RuntimeError: If the source can't be opened (CSV sources only,
            via X_POSSIBLE_NAMES/Y_POSSIBLE_NAMES) or the translate fails.
    """
    base_path, source_layer_name = _split_source_uri(source.path)
    if not os.path.exists(base_path):
        raise RuntimeError(f"Source file not found: {base_path}")
    source_ds = base_path
    extra_options = []

    if source.kind == "csv":
        source_ds = gdal.OpenEx(
            base_path,
            gdal.OF_VECTOR,
            open_options=[f"X_POSSIBLE_NAMES={source.x_field}", f"Y_POSSIBLE_NAMES={source.y_field}"],
        )
        if source_ds is None:
            raise RuntimeError(f"Could not open CSV '{source.path}' as a point source for '{source.layer_name}'")
    elif source_layer_name:
        # Select only the one layer the project actually configured -
        # without this, a multi-layer source (a GeoPackage with several
        # tables) would pull in every layer under this one name.
        extra_options = [source_layer_name]

    # clipSrc/clipSrcLayer as named kwargs need a newer GDAL than QGIS
    # 3.34 LTR bundles (3.4.1) - the "-clipsrc"/"-clipsrclayer" raw CLI
    # options have been supported since much older GDAL releases.
    options = gdal.VectorTranslateOptions(
        format="GPKG",
        layerName=source.layer_name,
        accessMode="append" if append else None,
        options=["-clipsrc", study_area_gpkg, "-clipsrclayer", study_area_layer] + extra_options,
    )
    result = gdal.VectorTranslate(out_gpkg, source_ds, options=options)
    if result is None:
        raise RuntimeError(f"Failed to write vector '{source.layer_name}': {gdal.GetLastErrorMsg()}")
    result = None  # noqa: F841 - closes/flushes the dataset


def _apply_style(uri: str, is_raster: bool, style_xml: str) -> None:
    """Embed a style into a just-written GPKG layer's layer_styles table.

    Args:
        uri: QGIS data source URI for the layer just written (e.g.
            "GPKG:out.gpkg:Fire" for a raster, "out.gpkg|layername=Fire"
            for a vector).
        is_raster: Whether the layer is a raster.
        style_xml: Style XML previously exported from a live layer (see
            the module docstring - this must be resolved on the main
            thread, never read here).
    """
    layer = QgsRasterLayer(uri, "style-target") if is_raster else QgsVectorLayer(uri, "style-target", "ogr")
    if not layer.isValid():
        log_message(f"Could not reopen '{uri}' to apply style - skipping.", tag="GeoE3")
        return
    doc = QDomDocument()
    doc.setContent(style_xml)
    success, message = layer.importNamedStyle(doc)
    if not success:
        log_message(f"Could not import style for '{uri}': {message}", tag="GeoE3")
        return
    error = layer.saveStyleToDatabase("default", "country pack source style", True, "")
    if error:
        log_message(f"Could not save style for '{uri}' into the pack: {error}", tag="GeoE3")


def build_country_pack(
    working_directory: str,
    model: dict,
    output_path: str,
    style_xml_by_path: Optional[Dict[str, str]] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, List[str]]:
    """Build a single country pack GeoPackage from a project's configured inputs.

    Args:
        working_directory: The project's working directory (where
            study_area/study_area.gpkg lives).
        model: The already-parsed model.json document.
        output_path: Path the pack GeoPackage should be written to. Any
            existing file at this path is removed first.
        style_xml_by_path: Source path -> style XML, for sources whose
            style should be embedded (resolved on the main thread - see
            the module docstring).
        progress_callback: Optional callback(done_count, total_count,
            current_layer_name), called after each source is processed.

    Returns:
        {"written": [...], "skipped": [...]} - layer names written, and
        source paths that failed and were skipped (the pack still
        contains everything that succeeded).
    """
    style_xml_by_path = style_xml_by_path or {}
    study_area_gpkg = os.path.join(working_directory, "study_area", "study_area.gpkg")
    study_area_layer = "study_area_clip_polygons"

    if os.path.exists(output_path):
        os.remove(output_path)

    sources = all_sources(model)
    written: List[str] = []
    skipped: List[str] = []

    for index, source in enumerate(sources):
        if progress_callback:
            progress_callback(index, len(sources), source.layer_name)
        try:
            # GDAL's GPKG driver recreates the whole file from scratch
            # unless told to append - wiping out whatever's already in
            # it, vector or raster alike. So "append" has to mean "does
            # the output file exist yet at all", checked fresh each
            # write, not "have I already written a layer of this same
            # kind" - the latter let a raster write silently destroy an
            # earlier vector layer the first time the source list
            # switched from vector sources to raster ones (caught via a
            # real end-to-end run: road_network vanished the moment the
            # first raster was appended after it).
            append = os.path.exists(output_path)
            if source.kind == "raster":
                write_raster_source(source, study_area_gpkg, study_area_layer, output_path, append)
                uri = f"GPKG:{output_path}:{source.layer_name}"
                is_raster = True
            else:
                write_vector_source(source, study_area_gpkg, study_area_layer, output_path, append)
                uri = f"{output_path}|layername={source.layer_name}"
                is_raster = False

            style_xml = style_xml_by_path.get(source.path.split("|")[0])
            if style_xml:
                _apply_style(uri, is_raster, style_xml)

            written.append(source.layer_name)
        except Exception as e:
            # Broad on purpose: a missing/moved/corrupted input is a real
            # possibility across 19+ independently-configured sources, and
            # GDAL's own failure mode for "file genuinely doesn't exist" is
            # not always a clean, catchable RuntimeError - confirmed to
            # sometimes surface as a raw TypeError from the SWIG binding
            # layer instead. One bad source should drop into "skipped",
            # not abort the whole pack.
            log_message(f"Skipping '{source.layer_name}': {e}", tag="GeoE3")
            skipped.append(source.layer_name)

    if progress_callback:
        progress_callback(len(sources), len(sources), "")

    return {"written": written, "skipped": skipped}
