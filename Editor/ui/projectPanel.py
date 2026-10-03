# -*- coding: utf-8 -*-
"""项目面板：列出项目 Resources 目录下的资源文件。

右键菜单（V3）：
- 导入模型…：选择 .obj 复制进 Resources/Models（onImport 回调给 main）
- 刷新：重新扫描目录
- 重命名：就地改名（tkinter 简单对话框）
- 删除：确认后删除文件
双击 .obj 文件 = 「使用」：onUseMesh 回调（main 里给选中物体换网格或创建新物体）
"""

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from ..core.meshCache import importModel


class ProjectPanel(tk.Frame):
    """项目文件夹（Resources）下的文件树 + 右键操作。"""

    def __init__(self, master, projectRoot=None, onImport=None, onUseMesh=None,
                 onStatus=None, **kw):
        super().__init__(master, **kw)
        self.projectRoot = Path(projectRoot) if projectRoot else None
        self.onImport = onImport          # 导入完成回调（main 刷新网格下拉等）
        self.onUseMesh = onUseMesh        # 双击 .obj：使用该模型
        self.onStatus = onStatus          # 状态栏消息回调
        ttk.Label(self, text="项目", padding=(6, 3)).pack(fill=tk.X)
        self.tree = ttk.Treeview(self, show="tree")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Button-3>", self._onRightClick)
        self.tree.bind("<Double-1>", self._onDoubleClick)
        self.refresh()

    # ---- 目录扫描 ----
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

    # ---- 路径工具 ----
    def _selectedPath(self):
        """当前选中项的完整路径；无选中/根目录返回 None。"""
        sel = self.tree.selection()
        if not sel:
            return None
        item = sel[0]
        # 收集从根到该项的名字链
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

    # ---- 右键菜单 ----
    def _onRightClick(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
        path = self._selectedPath()
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="导入模型…", command=self._importModel)
        menu.add_command(label="刷新", command=self.refresh)
        if path is not None and path != self.projectRoot:
            menu.add_separator()
            menu.add_command(label="重命名", command=self._renamePath)
            menu.add_command(label="删除", command=self._deletePath)
        menu.tk_popup(event.x_root, event.y_root)

    def _importModel(self):
        """导入 .obj 模型到 Resources/Models。"""
        if self.projectRoot is None:
            messagebox.showinfo("项目", "当前没有打开项目，无法导入资源。")
            return
        file = filedialog.askopenfilename(
            title="导入 .obj 模型", filetypes=[("OBJ 模型", "*.obj"), ("所有文件", "*.*")])
        if not file:
            return
        try:
            rel = importModel(Path(file), self.projectRoot)
        except (OSError, ValueError) as e:
            messagebox.showerror("导入失败", str(e))
            return
        self.refresh()
        self._status(f"已导入模型 {rel}")
        if self.onImport:
            self.onImport(rel)

    def _renamePath(self):
        path = self._selectedPath()
        if path is None or not path.exists():
            return
        newName = simpledialog.askstring("重命名", "新名称：", initialvalue=path.name)
        if not newName or newName == path.name:
            return
        target = path.parent / newName
        if target.exists():
            messagebox.showerror("重命名", f"已存在同名文件/目录：{newName}")
            return
        try:
            path.rename(target)
        except OSError as e:
            messagebox.showerror("重命名", str(e))
            return
        self.refresh()
        self._status(f"已重命名 {path.name} → {newName}")

    def _deletePath(self):
        path = self._selectedPath()
        if path is None or not path.exists():
            return
        if not messagebox.askyesno("删除", f"确定删除「{path.name}」？\n此操作不可撤销。"):
            return
        try:
            if path.is_dir():
                import shutil
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as e:
            messagebox.showerror("删除", str(e))
            return
        self.refresh()
        self._status(f"已删除 {path.name}")

    # ---- 双击使用 ----
    def _onDoubleClick(self, event):
        path = self._selectedPath()
        if path is None or not path.is_file() or path.suffix.lower() != ".obj":
            return
        # 相对 Resources 的路径才是 mesh 键
        rel = path.relative_to(self.projectRoot / "Resources").as_posix()
        if self.onUseMesh:
            self.onUseMesh(rel)

    def _status(self, msg):
        if self.onStatus:
            try:
                self.onStatus(msg)
            except Exception:
                pass
