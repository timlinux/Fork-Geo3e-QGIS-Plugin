# The Analysis Report & Raw Data

!!! abstract "Learning objective"
    By the end of this page you'll know how to navigate the PDF analysis
    report GeoE3 generates after every run, interpret its correlation and
    color-matrix pages, and get at the raw grid results yourself —
    whether that's loading them as a vector/raster layer or exporting to
    CSV for a spreadsheet or statistics package.

Every time an analysis finishes, GeoE3 also writes a full PDF report
summarizing everything it did. Pull it up any time by right-clicking the
analysis node and choosing **Show Analysis Report** — it can take a
couple of minutes to generate on a large study area.

## Reading the report

The report follows a fixed structure, front to back:

1. **Credits and attribution** for the project's funders and the data
   sources used.
2. **Legend pages** explaining the 5-class enablement colour scheme and,
   if you've added population, the 15-class bivariate legend — both
   referenced throughout the rest of the report.
3. **Every analysis output**, from the overall GeoE3 score down through
   each dimension, factor and indicator, each with a sparkline-style bar
   chart showing what proportion of cells fell into each class.
4. **Subnational breakdowns**, if you configured an aggregation boundary —
   majority GeoE3 score per region, by population, and masked by
   settlement layer.
5. **A colour matrix**: every subnational district as a row, every factor
   as a column, each cell shaded by that district's score for that
   factor — a fast way to spot outliers.
6. **A correlation heatmap** between factors.
7. **A methodology diagram and explanation**, plus the scoring weights
   actually used in this run.
8. **Processing time notes** at the very end — how long each step took,
   useful if you're trying to work out why something is slow.

<figure markdown>
![An analysis report page showing the 0–5 scoring methodology and a factor-correlation heatmap legend](../images/training/report-methodology-scale.jpg)
<figcaption>The methodology page states the scale explicitly: every indicator is scored 0–5 per grid cell, combined up through factor, dimension and overall GeoE3 scores by the weights you configured.</figcaption>
</figure>

### Making sense of the correlation heatmap

Row and column numbers both refer to the same ordered list of factors —
cell (3, 7) compares factor 3 against factor 7. The diagonal (where a
factor is compared against itself) is always the deepest shade and isn't
a finding. Off the diagonal: deep blue means the two factors tend to
score high in the same places (if one is high, so is the other); deep red
means they move in opposite directions; pale means no real relationship.
It's a quick way to spot patterns — for example, poor access to public
transport tends to track with poor water and sanitation access in the
same places, which can point to a broader infrastructure gap rather than
an isolated issue.

## Accessing the raw data yourself

The report is a summary — the underlying grid, with a score for every
indicator, factor and dimension in every cell, is also available for you
to work with directly.

GeoE3 adds a nested layer-group structure to your project mirroring the
model tree. Right-click any node in it and you'll see a set of **Add…**
options:

- **Add GeoE3 Score to Map** — as a vector grid or a rasterized grid.
  The vector version is the one to use if you want the numbers: open its
  attribute table and every indicator, factor and dimension score is
  there as a column, ready to **export as CSV** for a spreadsheet,
  statistics package, or your own further analysis.
- **Add GeoE3 Aggregates to Map** — the subnational bivariate layer
  described above. Use the **Identify** tool to click a region and see
  its name and majority score.
- **Add GHSL Settlements to Map** — the settlement vector layer used for
  masking, if you configured one.
- **Open Working Directory** — jumps straight to the project folder
  holding every output and report this analysis produced.

!!! success "Recap"
    - **Show Analysis Report** on the analysis node generates a full PDF:
      legends, every output with its distribution, subnational
      breakdowns, a factor correlation heatmap, and the methodology and
      weights actually used.
    - The correlation heatmap's diagonal is never a finding — look off
      it for factors that move together (blue) or oppose each other
      (red).
    - The underlying grid is yours to use beyond QGIS: add it as a
      vector layer and export its attribute table to CSV for further
      analysis elsewhere.

That's the complete walkthrough — from an empty QGIS install through to a
finished, reportable analysis. From here, the [Legacy Detailed
Reference](../about/legacy-detailed-reference.md) covers a few individual
factors in more granular detail, and [About](../about/index.md) has the
background on the framework this tool implements.
