"""Custom QStyledItemDelegate for the thumbnail grid."""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize, QRect, QPoint
from PySide6.QtGui import QPainter, QPixmap, QColor, QFont, QPen, QFontMetrics
from PySide6.QtWidgets import QStyledItemDelegate, QApplication, QStyle

from ..models import FileItem, Role


class ThumbnailDelegate(QStyledItemDelegate):
    PADDING = 6
    LABEL_H = 32  # height reserved for filename label

    def sizeHint(self, option, index) -> QSize:
        item: FileItem = index.data(Role.ITEM)
        if item is None:
            return QSize(128, 128 + self.LABEL_H)
        thumb_size = item.thumb_size
        return QSize(thumb_size + self.PADDING * 2,
                     thumb_size + self.LABEL_H + self.PADDING * 2)

    def paint(self, painter: QPainter, option, index) -> None:
        item: FileItem = index.data(Role.ITEM)
        if item is None:
            return

        painter.save()
        thumb_size = item.thumb_size
        cell_w = option.rect.width()
        cell_h = option.rect.height()
        ox = option.rect.x()
        oy = option.rect.y()

        # Background
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if is_selected:
            bg = QColor(60, 120, 200, 160)
        elif bool(option.state & QStyle.StateFlag.State_MouseOver):
            bg = QColor(80, 80, 90, 120)
        else:
            bg = QColor(40, 40, 48)
        painter.fillRect(option.rect, bg)

        # Thumbnail image
        pixmap: QPixmap | None = index.data(Role.PIXMAP)
        img_x = ox + (cell_w - thumb_size) // 2
        img_y = oy + self.PADDING

        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(
                thumb_size, thumb_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            draw_x = img_x + (thumb_size - scaled.width()) // 2
            draw_y = img_y + (thumb_size - scaled.height()) // 2
            painter.drawPixmap(draw_x, draw_y, scaled)
        else:
            # Spinner / loading placeholder
            painter.setPen(QPen(QColor(100, 100, 120), 1))
            painter.drawRect(img_x, img_y, thumb_size, thumb_size)
            painter.setPen(QColor(140, 140, 160))
            painter.drawText(
                QRect(img_x, img_y, thumb_size, thumb_size),
                Qt.AlignmentFlag.AlignCenter, "…"
            )

        # Sequence badge
        if item.is_sequence and item.frame_count > 1:
            badge = f"×{item.frame_count}"
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 180))
            bw, bh = 50, 18
            bx = ox + cell_w - bw - 4
            by = img_y + 4
            painter.drawRoundedRect(bx, by, bw, bh, 4, 4)
            painter.setPen(QColor(200, 240, 200))
            font = painter.font()
            font.setPointSize(7)
            painter.setFont(font)
            painter.drawText(QRect(bx, by, bw, bh), Qt.AlignmentFlag.AlignCenter, badge)

        # Format badge
        fmt_label = item.format_label
        if fmt_label:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 150))
            fl = fmt_label[:6]
            fw = len(fl) * 6 + 8
            fh = 16
            painter.drawRoundedRect(img_x + 2, img_y + 2, fw, fh, 3, 3)
            painter.setPen(QColor(220, 220, 180))
            font2 = painter.font()
            font2.setPointSize(7)
            painter.setFont(font2)
            painter.drawText(QRect(img_x + 2, img_y + 2, fw, fh),
                             Qt.AlignmentFlag.AlignCenter, fl)

        # Filename label
        label_rect = QRect(ox + 2, oy + self.PADDING + thumb_size + 2,
                           cell_w - 4, self.LABEL_H)
        painter.setPen(QColor(210, 210, 220))
        font3 = painter.font()
        font3.setPointSize(8)
        painter.setFont(font3)
        fm = QFontMetrics(font3)
        text = item.display_name
        elided = fm.elidedText(text, Qt.TextElideMode.ElideMiddle, label_rect.width())
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, elided)

        painter.restore()
