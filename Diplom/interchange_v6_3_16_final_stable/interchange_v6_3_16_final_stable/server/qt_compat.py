"""Qt compatibility for PySide6, PySide2 and PyQt5."""
import os


def _load_pyside6():
    from PySide6.QtCore import Qt, QObject, Signal, QTimer, QSize
    from PySide6.QtGui import QIcon, QPixmap
    from PySide6.QtWidgets import (
        QApplication, QFileDialog, QHBoxLayout, QLabel, QListWidget,
        QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
        QPushButton, QToolButton, QVBoxLayout, QWidget, QFrame,
        QAbstractItemView, QProgressBar, QDialog, QSpinBox, QTabWidget, QLineEdit,
        QTableWidget, QTableWidgetItem, QComboBox, QCheckBox,
        QHeaderView, QFormLayout, QGroupBox, QScrollArea
    )
    return locals()


def _load_pyside2():
    from PySide2.QtCore import Qt, QObject, Signal, QTimer, QSize
    from PySide2.QtGui import QIcon, QPixmap
    from PySide2.QtWidgets import (
        QApplication, QFileDialog, QHBoxLayout, QLabel, QListWidget,
        QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
        QPushButton, QToolButton, QVBoxLayout, QWidget, QFrame,
        QAbstractItemView, QProgressBar, QDialog, QSpinBox, QTabWidget, QLineEdit,
        QTableWidget, QTableWidgetItem, QComboBox, QCheckBox,
        QHeaderView, QFormLayout, QGroupBox, QScrollArea
    )
    return locals()


def _load_pyqt5():
    from PyQt5.QtCore import Qt, QObject, pyqtSignal as Signal, QTimer, QSize
    from PyQt5.QtGui import QIcon, QPixmap
    from PyQt5.QtWidgets import (
        QApplication, QFileDialog, QHBoxLayout, QLabel, QListWidget,
        QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
        QPushButton, QToolButton, QVBoxLayout, QWidget, QFrame,
        QAbstractItemView, QProgressBar, QDialog, QSpinBox, QTabWidget, QLineEdit,
        QTableWidget, QTableWidgetItem, QComboBox, QCheckBox,
        QHeaderView, QFormLayout, QGroupBox, QScrollArea
    )
    return locals()


def _export(values):
    for name, value in values.items():
        if not name.startswith("_"):
            globals()[name] = value


_preferred = os.environ.get("INTERCHANGE_QT_API", "").strip().lower()
if _preferred == "pyqt5":
    _qt = _load_pyqt5()
    QT_API = "PyQt5"
elif _preferred == "pyside2":
    _qt = _load_pyside2()
    QT_API = "PySide2"
elif _preferred == "pyside6":
    _qt = _load_pyside6()
    QT_API = "PySide6"
else:
    try:
        _qt = _load_pyside6()
        QT_API = "PySide6"
    except ImportError:
        try:
            _qt = _load_pyside2()
            QT_API = "PySide2"
        except ImportError:
            _qt = _load_pyqt5()
            QT_API = "PyQt5"

_export(_qt)


def app_exec(app):
    if hasattr(app, "exec"):
        return app.exec()
    return app.exec_()
