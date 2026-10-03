# -*- coding: utf-8 -*-
"""项目面板 —— 资源浏览器：浏览 / 创建 / 导入 / 双击打开项目内所有资源。

资源类型（V3.5）：
- .obj 模型（导入 / 双击 = 使用：换网格或建物体）
- .vmat 材质（创建 / 双击或单击 = 在检查器编辑颜色）
- .vscene 场景（创建 / 双击 = 打开场景）

右键菜单：创建场景 / 创建材质 / 导入模型 / 刷新 / 重命名 / 删除。
"""

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from ..core.materialCache import createMaterialFile
from ..core.meshCache import importModel
from ..core.scene import Scene
from ..core.serializer import saveSceneFile


class ProjectPanel(tk.Frame):
    """项目 Resources 资源浏览器。"""

    def __init__(self, master, projectRoot=None, onOpenScene=None,
                 onUseMesh=None, onEditMaterial=None, onImport=None,
                 onStatus=None, **kw):
        super().__init__(master, **kw)
        self.projectRoot = Path(projectRoot) if projectRoot else None
        self.onOpenScene = onOpenScene      # 双击 .vscene：打开场景
        self.onUseMesh = onUseMesh          # 双击 .obj：使用该模型
        self.onEditMaterial = onEditMaterial  # 选中/双击 .vmat：检查器编辑材质
        self.onImport = onImport            # 导入模型完成回调（刷新检查器网格下拉）
        self.onStatus = onStatus            # 状态栏消息回调
        ttk.Label(self, text="项目资源", padding=(6, 3)).pack(fill=tk.X)
        self.tree = ttk.Treeview(self, show="tree")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Button-3>", self._onRightClick)
        self.tree.bind("<Double-1>", self._onDoubleClick)
        self.tree.bind("<<TreeviewSelect>>", self._onSelect)
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
        else:
            self.tree.insert(root, tk.END, text="（没有 Resources 目录）")

    def _insertDir(self, directory, parent):
        for child in sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name)):
            if child.is_dir():
                node = self.tree.insert(parent, tk.END, text=child.name, open=False)
                self._insertDir(child, node)
            else:
                self.tree.insert(parent, tk.END, text=child.name, values=(child,))

    # ---- 路径工具 ----
    def _selectedPath(self):
        """当前选中项（文件）的完整路径；无选中/目录返回 None。"""
        sel = self.tree.selection()
        if not sel:
            return None
        item = sel[0]
        values = self.tree.item(item, "values")
        if values:
            return Path(values[0])
        return None

    def _relPath(self, path):
        """Resources 下的相对资源路径（材质/模型键用）。"""
        try:
            return path.relative_to(self.projectRoot / "Resources").as_posix()
        except ValueError:
            return None

    # ---- 选中（单击 .vmat → 检查器编辑材质） ----
    def _onSelect(self, _event):
        path = self._selectedPath()
        if path is None or not path.is_file():
            return
        if path.suffix.lower() == ".vmat" and self.onEditMaterial:
            rel = self._relPath(path)
            if rel:
                self.onEditMaterial(rel)

    # ---- 右键菜单 ----
    def _onRightClick(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="创建场景…", command=self._createScene)
        menu.add_command(label="创建材质…", command=self._createMaterial)
        menu.add_command(label="导入模型…", command=self._importModel)
        menu.add_command(label="刷新", command=self.refresh)
        path = self._selectedPath()
        if path is not None and path.exists():
            menu.add_separator()
            menu.add_command(label="重命名", command=self._renamePath)
            menu.add_command(label="删除", command=self._deletePath)
        menu.tk_popup(event.x_root, event.y_root)

    def _createScene(self):
        """在 Resources/Scenes 创建空 .vscene 场景文件。"""
        if self.projectRoot is None:
            messagebox.showinfo("项目", "当前没有打开项目，无法创建场景。")
            return
        name = simpledialog.askstring("创建场景", "场景名称：", initialvalue="新场景")
        if not name:
            return
        targetDir = self.projectRoot / "Resources" / "Scenes"
        targetDir.mkdir(parents=True, exist_ok=True)
        path = targetDir / f"{name}.vscene"
        n = 1
        while path.exists():
            path = targetDir / f"{name}{n}.vscene"
            n += 1
        saveSceneFile(Scene(), path)
        self.refresh()
        self._status(f"已创建场景 {path.stem}.vscene")

    def _createMaterial(self):
        """在 Resources/Materials 创建 .vmat 材质文件。"""
        if self.projectRoot is None:
            messagebox.showinfo("项目", "当前没有打开项目，无法创建材质。")
            return
        name = simpledialog.askstring("创建材质", "材质名称：", initialvalue="新材质")
        if not name:
            return
        rel = createMaterialFile(self.projectRoot, name=name)
        self.refresh()
        self._status(f"已创建材质 {rel}")

    def _importModel(self):
        """导入 .obj 模型到 Resources/Models（外部文件用系统选择器是唯一途径）。"""
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
            try:
                self.onImport(rel)
            except Exception:
                pass

    def _renamePath(self):
        path = self._selectedPath()
        if path is None or not path.exists():
            return
        newName = simpledialog.askstring("重命名", "新名称：", initialvalue=path.name)
        if not newName or newName == path.name:
            return
        target = path.parent / newName
        if target.exists():
            messagebox.showerror("重命名", f"已存在同名文件：{newName}")
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
            path.unlink()
        except OSError as e:
            messagebox.showerror("删除", str(e))
            return
        self.refresh()
        self._status(f"已删除 {path.name}")

    # ---- 双击打开 ----
    def _onDoubleClick(self, event):
        path = self._selectedPath()
        if path is None or not path.is_file():
            return
        suffix = path.suffix.lower()
        if suffix == ".vscene" and self.onOpenScene:
            self.onOpenScene(path)
        elif suffix == ".vmat" and self.onEditMaterial:
            rel = self._relPath(path)
            if rel:
                self.onEditMaterial(rel)
        elif suffix == ".obj" and self.onUseMesh:
            rel = self._relPath(path)
            if rel:
                self.onUseMesh(rel)

    def _status(self, msg):
        if self.onStatus:
            try:
                self.onStatus(msg)
            except Exception:
                pass
