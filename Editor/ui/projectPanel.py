# -*- coding: utf-8 -*-
"""项目面板：列出项目 Resources 目录下的资源文件（V2 只读浏览）。"""

from pathlib import Path
import tkinter as tk
from tkinter import ttk


class ProjectPanel(tk.Frame):
    """显示项目文件夹（Resources）下的文件树。"""

    def __init__(self, master, projectRoot=None, **kw):
        super().__init__(master, **kw)
        self.projectRoot = Path(projectRoot) if projectRoot else None
        ttk.Label(self, text="项目", padding=(6, 3)).pack(fill=tk.X)
        self.tree = ttk.Treeview(self, show="tree")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        if self.projectRoot is None or not self.projectRoot.is_dir():
            return
        root = self.tree.insert("", tk.END, text=self.projectRoot.name, open=True)
        resources = self.projectRoot / "Resources"
        if resources.is_dir():
            self._insertDir(resources, root)

    def _insertDir(self, directory, parent):
        for child in sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name)):
            if child.is_dir():
                node = self.tree.insert(parent, tk.END, text=child.name, open=False)
                self._insertDir(child, node)
            else:
                self.tree.insert(parent, tk.END, text=child.name)