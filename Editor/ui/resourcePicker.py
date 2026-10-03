# -*- coding: utf-8 -*-
"""项目资源选择器：模态对话框，选择项目 Resources 内的所有资源。

替代系统文件选择器（用户要求：选项目内资源不用系统对话框）：
- 树形列出 Resources 下全部文件，按目录分组
- 返回选中资源的相对路径（如 "Materials/red.vmat"）
- 可选按扩展名过滤（如只选 .vmat / .obj）
"""

import tkinter as tk
from pathlib import Path
from tkinter import ttk

RESOURCE_EXT = {".obj", ".vmat", ".vscene"}


class ResourcePicker(tk.Toplevel):
    """选择项目资源。confirm() 返回相对资源路径或 None。"""

    def __init__(self, master, projectRoot, title="选择资源",
                 extensions=None, prompt="选择项目资源："):
        super().__init__(master)
        self.projectRoot = Path(projectRoot) if projectRoot else None
        self.extensions = set(extensions) if extensions else None   # None=全部资源
        self.result = None
        self.title(title)
        self.geometry("460x520")
        self.transient(master)
        self.grab_set()
        self.resizable(True, True)
        self._build(prompt)
        self._load()

    # ---- 构建 ----
    def _build(self, prompt):
        ttk.Label(self, text=prompt, padding=(8, 6)).pack(fill=tk.X)
        self.tree = ttk.Treeview(self, show="tree", selectmode="browse")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))
        self.tree.bind("<Double-1>", lambda _e: self._choose())
        self.tree.bind("<Return>", lambda _e: self._choose())
        btns = ttk.Frame(self)
        btns.pack(fill=tk.X, padx=8, pady=(0, 8))
        ttk.Button(btns, text="确定", command=self._choose).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side=tk.RIGHT)

    def _load(self):
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
                if self.extensions is not None and child.suffix.lower() not in self.extensions:
                    continue
                self.tree.insert(parent, tk.END, text=child.name,
                                 values=(child,))

    # ---- 结果 ----
    def _selectedPath(self):
        sel = self.tree.selection()
        if not sel:
            return None
        item = sel[0]
        values = self.tree.item(item, "values")
        if values:   # 叶子（文件）
            return Path(values[0])
        # 目录：收集名字链
        chain = [self.tree.item(item, "text")]
        while True:
            parent = self.tree.parent(item)
            if not parent:
                break
            chain.append(self.tree.item(parent, "text"))
            item = parent
        chain.reverse()
        path = self.projectRoot
        for part in chain:
            path = path / part
        return path

    def _choose(self):
        path = self._selectedPath()
        if path is not None and path.is_file():
            self.result = path.relative_to(self.projectRoot / "Resources").as_posix()
            self.destroy()
