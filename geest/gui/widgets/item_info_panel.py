# -*- coding: utf-8 -*-
"""📦 Item info panel module.

A collapsible panel shown above the tree panel's button row (the same
space the progress bars occupy during a run - both are empty/visible
at different times, never at once) explaining whatever tree item is
currently selected: a heading, a short description and an icon. For
an indicator, a "Methodology" link slides over to a second page
showing the real-world technique behind its score - the same name,
description and icon used on the analysis report's own Methodology
pages (geest/core/reports/methodology.py) - so the explanation stays
in sync with what gets published.

Replaces the old `LayerDescriptionItem` map-canvas overlay, which had
been disabled since May 2026 and, per user feedback, wasn't the right
pattern anyway: a dock panel next to the controls the user is already
looking at beats a floating label on the map.
"""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from geest.core.reports.methodology import TECHNIQUES, technique_for_analysis_mode
from geest.core.topic_icons import topic_icon_filename
from geest.utilities import resources_path

NAVY = "#002244"
CYAN = "#009FDA"
CHARCOAL = "#333333"
GREY = "#6E7B85"
MIST = "#EEF4F8"
RULE = "#D6DEE4"
ICON_TILE_BG = "#E3F3FB"

_ROLE_LABELS = {
    "dimension": "Dimension",
    "factor": "Factor",
    "indicator": "Indicator",
    "analysis": "Analysis",
}


def _truncate(text: str, limit: int = 130) -> str:
    """A one-glance summary, cut at a word boundary rather than a
    sentence boundary - a technique's first sentence can itself run
    well past a card-sized budget (e.g. "feature_count"'s, at an
    em-dash clause), so splitting on ". " doesn't reliably bound the
    length the way a flat character limit does.
    """
    text = text.strip()
    if len(text) <= limit:
        return text if text.endswith((".", "…")) else f"{text}."
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;: ") + "…"


class ItemInfoPanel(QWidget):
    """Collapsible "what is this item" panel with a methodology slide-over."""

    #: Emitted whenever the user's expand/collapse choice changes, so the
    #: host layout can be told whether this widget just changed its own
    #: preferred height (there is nothing else to resize for).
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        """🏗️ Initialize the instance.

        Args:
            parent: Parent widget.
        """
        super().__init__(parent)
        self._expanded = True
        self._current_technique_key = None
        self._build_ui()
        self.clear()

    def _build_ui(self):
        """⚙️ Build the static widget structure (header + two stacked pages)."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.setStyleSheet(
            f"""
            QFrame#itemInfoCard {{
                background-color: {MIST};
                border: 1px solid {RULE};
                border-radius: 6px;
            }}
            QToolButton#collapseToggle {{
                border: none;
                color: {GREY};
                font-weight: bold;
            }}
            QLabel#headingLabel {{
                color: {NAVY};
                font-weight: bold;
                font-size: 11pt;
            }}
            QLabel#bodyLabel {{
                color: {CHARCOAL};
                font-size: 9pt;
            }}
            QLabel#metaLabel {{
                color: {GREY};
                font-size: 8.5pt;
            }}
            QToolButton#moreLink, QToolButton#backLink {{
                border: none;
                color: {CYAN};
                font-weight: bold;
                font-size: 9pt;
            }}
            QLabel#iconTile {{
                background-color: {ICON_TILE_BG};
                border: 1px solid {RULE};
                border-radius: 8px;
            }}
            """
        )

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(6, 2, 6, 2)
        self.header_label = QLabel("Selected item")
        self.header_label.setStyleSheet(f"color: {GREY}; font-size: 8pt; font-weight: bold;")
        header_layout.addWidget(self.header_label)
        header_layout.addStretch(1)
        self.collapse_button = QToolButton()
        self.collapse_button.setObjectName("collapseToggle")
        self.collapse_button.setText("▾")
        self.collapse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_button.clicked.connect(self.toggle_expanded)
        header_layout.addWidget(self.collapse_button)
        outer.addWidget(header)

        self.card = QFrame()
        self.card.setObjectName("itemInfoCard")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(8, 6, 8, 8)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_item_page())
        self.stack.addWidget(self._build_methodology_page())
        card_layout.addWidget(self.stack)

        outer.addWidget(self.card)
        self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # A fixed cap, not just a Fixed size policy: without this the card
        # still happily grows to fill whatever room the host layout hands
        # it (Fixed only stops it growing to match its OWN size hint, not
        # the hint of an empty/short-content hint being stretched by a
        # parent that has nothing else competing for that space).
        self.card.setMaximumHeight(112)

    def _build_item_page(self) -> QWidget:
        """⚙️ Build the "currently selected item" page.

        Returns:
            The page widget.
        """
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)

        self.item_icon_label = QLabel()
        self.item_icon_label.setObjectName("iconTile")
        self.item_icon_label.setFixedSize(36, 36)
        self.item_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.item_icon_label, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        self.item_heading_label = QLabel("")
        self.item_heading_label.setObjectName("headingLabel")
        self.item_heading_label.setWordWrap(True)
        text_col.addWidget(self.item_heading_label)

        # One combined "Role · description" line instead of two separate
        # labels - a bare item with no custom description has nothing to
        # say beyond its own role, so showing the role twice (once as a
        # badge, once as getItemTooltip()'s "Indicator"/"Factor"/...
        # fallback body text) was pure redundant clutter.
        self.item_meta_label = QLabel("")
        self.item_meta_label.setObjectName("metaLabel")
        self.item_meta_label.setWordWrap(True)
        text_col.addWidget(self.item_meta_label)

        self.more_link = QToolButton()
        self.more_link.setObjectName("moreLink")
        self.more_link.setText("Methodology  →")
        self.more_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_link.clicked.connect(self._show_methodology_page)
        self.more_link.setVisible(False)
        text_col.addWidget(self.more_link, 0, Qt.AlignmentFlag.AlignLeft)

        text_col.addStretch(1)
        row.addLayout(text_col, 1)
        return page

    def _build_methodology_page(self) -> QWidget:
        """⚙️ Build the methodology slide-over page.

        Returns:
            The page widget.
        """
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        self.back_link = QToolButton()
        self.back_link.setObjectName("backLink")
        self.back_link.setText("←  Selected item")
        self.back_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_link.clicked.connect(self._show_item_page)
        outer.addWidget(self.back_link, 0, Qt.AlignmentFlag.AlignLeft)

        row = QHBoxLayout()
        self.methodology_icon_label = QLabel()
        self.methodology_icon_label.setObjectName("iconTile")
        self.methodology_icon_label.setFixedSize(36, 36)
        self.methodology_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.methodology_icon_label, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        self.methodology_heading_label = QLabel("")
        self.methodology_heading_label.setObjectName("headingLabel")
        self.methodology_heading_label.setWordWrap(True)
        text_col.addWidget(self.methodology_heading_label)

        self.methodology_body_label = QLabel("")
        self.methodology_body_label.setObjectName("bodyLabel")
        self.methodology_body_label.setWordWrap(True)
        text_col.addWidget(self.methodology_body_label)

        row.addLayout(text_col, 1)
        outer.addLayout(row)
        outer.addStretch(1)
        return page

    def toggle_expanded(self):
        """⚙️ Toggle between expanded and collapsed."""
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool):
        """⚙️ Show or hide the card, keeping only the slim header visible when collapsed.

        Args:
            expanded: Whether the card should be visible.
        """
        self._expanded = expanded
        self.card.setVisible(expanded)
        self.collapse_button.setText("▾" if expanded else "▸")
        self.toggled.emit(expanded)

    def clear(self):
        """⚙️ Show a neutral placeholder when nothing is selected."""
        self._current_technique_key = None
        self.item_icon_label.clear()
        self.item_heading_label.setText("No item selected")
        self.item_meta_label.setText("Click a dimension, factor or indicator in the tree to see details here.")
        self.more_link.setVisible(False)
        self._show_item_page()

    def _topic_icon(self, role: str, item_id: str):
        """⚙️ Load the topic-relevant icon for a role/id, or None if unmapped.

        Args:
            role: "analysis", "dimension", "factor" or "indicator".
            item_id: the item's ``id`` attribute.

        Returns:
            A QIcon, or None when no topic icon is mapped for this item.
        """
        filename = topic_icon_filename(role, item_id)
        if not filename:
            return None
        icon = QIcon(resources_path("resources", "icons", "topics", filename))
        return icon if not icon.isNull() else None

    def show_item(self, item) -> None:
        """⚙️ Update the panel for the given tree item.

        Args:
            item: The JsonTreeItem the user just clicked.
        """
        role = getattr(item, "role", "")
        item_id = item.attribute("id", "") if hasattr(item, "attribute") else ""
        icon = self._topic_icon(role, item_id)
        if icon is None and hasattr(item, "getIcon"):
            icon = item.getIcon()
        if isinstance(icon, QIcon) and not icon.isNull():
            self.item_icon_label.setPixmap(icon.pixmap(24, 24))
        else:
            self.item_icon_label.clear()

        name = item.data(0) if hasattr(item, "data") else str(item)
        self.item_heading_label.setText(name or "")

        role_label = _ROLE_LABELS.get(role, role.title() if role else "")
        description = item.attribute("description", "") if hasattr(item, "attribute") else ""
        if not description and hasattr(item, "getItemTooltip"):
            tooltip = item.getItemTooltip()
            # getItemTooltip() falls back to the bare role name itself
            # ("Indicator", "Factor", ...) when there's nothing more
            # specific to say - that's not a real description, just the
            # same word the role label already shows.
            if tooltip and tooltip != role_label:
                description = tooltip
        self.item_meta_label.setText(f"{role_label} · {description}" if description else role_label)

        analysis_mode = item.attribute("analysis_mode", "") if hasattr(item, "attribute") else ""
        technique_key = technique_for_analysis_mode(analysis_mode) if analysis_mode else None
        self._current_technique_key = technique_key
        self.more_link.setVisible(technique_key is not None)
        self._show_item_page()

    def _show_item_page(self):
        """⚙️ Switch the stack to the "selected item" page."""
        self.stack.setCurrentIndex(0)

    def _show_methodology_page(self):
        """⚙️ Switch the stack to the methodology page for the current item."""
        if self._current_technique_key is None:
            return
        technique = TECHNIQUES[self._current_technique_key]
        icon = QIcon(resources_path("resources", "methodology", technique["svg"]))
        if not icon.isNull():
            self.methodology_icon_label.setPixmap(icon.pixmap(24, 24))
        self.methodology_heading_label.setText(technique["name"])
        self.methodology_body_label.setText(_truncate(technique["description"]))
        self.stack.setCurrentIndex(1)
