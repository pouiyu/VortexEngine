# -*- coding: utf-8 -*-
"""项目面板 —— 资源浏览器：浏览 / 创建 / 导入 / 双击打开 / 拖拽 / 复制项目内所有资源。

资源类型（V4）：
- .obj 模型（导入 / 双击 = 使用：换网格或建物体）
- .vmat 材质（创建 / 单击或双击 = 在检查器编辑颜色）
- .vscene 场景（创建 / 双击 = 打开场景）

交互：
- 右键：新建文件夹 / 创建场景 / 创建材质 / 导入模型 / 刷新 / 重命名 / 删除
- 创建与导入都落在「当前选中目录」（不自动建子文件夹，完全自由）
- 拖拽资源/文件夹到另一目录 = 移动
- Ctrl+C / Ctrl+V：复制资源（文件或整目录）到当前目录
"""

import shutil
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
        self._clipboard = None              # Ctrl+C 复制源（Path）
        self._dragSource = None
        self._pressPos = None
        ttk.Label(self, text="项目资源", padding=(6, 3)).pack(fill=tk.X)
        self.tree = ttk.Treeview(self, show="tree")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Button-3>", self._onRightClick)
        self.tree.bind("<Double-1>", self._onDoubleClick)
        self.tree.bind("<<TreeviewSelect>>", self._onSelect)
        self.tree.bind("<ButtonPress-1>", self._onPress)
        self.tree.bind("<ButtonRelease-1>", self._onRelease)
        self.tree.bind("<Control-c>", self._onCopy)
        self.tree.bind("<Control-v>", self._onPaste)
        self.refresh()

    # ---- 目录扫描 ----
    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self._dragSource = None
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
        """当前选中项（文件或目录）的完整路径；无选中返回 None。"""
        sel = self.tree.selection()
        if not sel:
            return None
        item = sel[0]
        values = self.tree.item(item, "values")
        if values:
            return Path(values[0])
        # 目录：按名字链拼出完整路径
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

    def _resourcesDir(self):
        return self.projectRoot / "Resources"

    def _currentDir(self):
        """创建/导入/粘贴的目标目录：选中目录本身，选中文件或未选中 → 其父目录。"""
        path = self._selectedPath()
        if path is None:
            return self._resourcesDir()
        if path.is_dir():
            return path
        return path.parent

    def _relPath(self, path):
        """Resources 下的相对资源路径（材质/模型键用）。"""
        try:
            return path.relative_to(self._resourcesDir()).as_posix()
        except ValueError:
            return None

    def _isDirItem(self, item):
        """tree item 是否代表目录（无 values 字段 = 目录）。"""
        return not self.tree.item(item, "values")

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
        menu.add_command(label="新建文件夹…", command=self._newFolder)
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

    def _newFolder(self):
        """在「当前目录」下新建文件夹（不自动建任何子目录）。"""
        name = simpledialog.askstring("新建文件夹", "文件夹名称：", initialvalue="新文件夹")
        if not name:
            return
        target = self._currentDir() / name
        if target.exists():
            messagebox.showerror("新建文件夹", f"已存在同名项：{name}")
            return
        try:
            target.mkdir()
        except OSError as e:
            messagebox.showerror("新建文件夹", str(e))
            return
        self.refresh()
        self._status(f"已创建文件夹 {name}")

    def _createScene(self):
        """在「当前目录」创建空 .vscene 场景文件。"""
        if self.projectRoot is None:
            messagebox.showinfo("项目", "当前没有打开项目，无法创建场景。")
            return
        name = simpledialog.askstring("创建场景", "场景名称：", initialvalue="新场景")
        if not name:
            return
        targetDir = self._currentDir()
        path = targetDir / f"{name}.vscene"
        n = 1
        while path.exists():
            path = targetDir / f"{name}{n}.vscene"
            n += 1
        saveSceneFile(Scene(), path)
        self.refresh()
        self._status(f"已创建场景 {path.stem}.vscene")

    def _createMaterial(self):
        """在「当前目录」创建 .vmat 材质文件。"""
        if self.projectRoot is None:
            messagebox.showinfo("项目", "当前没有打开项目，无法创建材质。")
            return
        name = simpledialog.askstring("创建材质", "材质名称：", initialvalue="新材质")
        if not name:
            return
        rel = createMaterialFile(self.projectRoot, name=name,
                                 subdir=self._subdirOf(self._currentDir()))
        self.refresh()
        self._status(f"已创建材质 {rel}")

    def _importModel(self):
        """导入 .obj 模型到「当前目录」（外部文件用系统选择器是唯一途径）。"""
        if self.projectRoot is None:
            messagebox.showinfo("项目", "当前没有打开项目，无法导入资源。")
            return
        file = filedialog.askopenfilename(
            title="导入 .obj 模型", filetypes=[("OBJ 模型", "*.obj"), ("所有文件", "*.*")])
        if not file:
            return
        try:
            rel = importModel(Path(file), self.projectRoot,
                              subdir=self._subdirOf(self._currentDir()))
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

    def _subdirOf(self, directory):
        """目录 → 相对 Resources 的路径（Resources 根返回空串）。"""
        try:
            return directory.relative_to(self._resourcesDir()).as_posix()
        except ValueError:
            return ""

    def _renamePath(self):
        path = self._selectedPath()
        if path is None or not path.exists():
            return
        newName = simpledialog.askstring("重命名", "新名称：", initialvalue=path.name)
        if not newName or newName == path.name:
            return
        target = path.parent / newName
        if target.exists():
            messagebox.showerror("重命名", f"已存在同名项：{newName}")
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
        kind = "文件夹" if path.is_dir() else "文件"
        if not messagebox.askyesno("删除", f"确定删除{kind}「{path.name}」？\n此操作不可撤销。"):
            return
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as e:
            messagebox.showerror("删除", str(e))
            return
        self.refresh()
        self._status(f"已删除 {path.name}")

    # ---- 拖拽移动 ----
    def _onPress(self, event):
        self._pressPos = (event.x, event.y)
        item = self.tree.identify_row(event.y)
        self._dragSource = item if item else None

    def _onRelease(self, event):
        source = self._dragSource
        self._dragSource = None
        if source is None:
            return
        if self._pressPos and (abs(event.x - self._pressPos[0]) +
                               abs(event.y - self._pressPos[1])) < 5:
            return   # 视为点击/双击
        srcPath = self._treePath(source)
        if srcPath is None:
            return
        target = self.tree.identify_row(event.y)
        if target == source:
            return
        if target and self._isDirItem(target):
            dst = self._treePath(target)
            if dst is None:
                return
            # 目录不能拖进自己或自己子孙
            if srcPath.is_dir():
                if dst.resolve() == srcPath.resolve() or \
                   srcPath.resolve() in dst.resolve().parents:
                    return
            self._movePath(srcPath, dst)
        # 拖到文件/空白 = 忽略

    def _movePath(self, src, dstDir):
        if dstDir.resolve() == src.parent.resolve():
            return
        target = dstDir / src.name
        n = 1
        while target.exists():
            base = f"{src.stem} 副本" if src.is_file() else src.name
            target = dstDir / f"{base}{n}{src.suffix if src.is_file() else ''}"
            n += 1
        try:
            src.rename(target)
        except OSError as e:
            messagebox.showerror("移动失败", str(e))
            return
        self.refresh()
        self._status(f"已移动 {src.name}")

    def _treePath(self, item):
        """tree item → 完整路径（文件或目录）。"""
        values = self.tree.item(item, "values")
        if values:
            return Path(values[0])
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

    # ---- 复制 / 粘贴 ----
    def _onCopy(self, _event):
        path = self._selectedPath()
        if path is None or not path.exists():
            return
        self._clipboard = path
        self._status(f"已复制 {path.name}")
        return "break"

    def _onPaste(self, _event):
        if self._clipboard is None or not self._clipboard.exists():
            self._status("剪贴板没有资源")
            return "break"
        dstDir = self._currentDir()
        src = self._clipboard
        if src.is_dir():
            newPath = dstDir / f"{src.name} 副本"
            n = 1
            while newPath.exists():
                newPath = dstDir / f"{src.name} 副本{n}"
                n += 1
            try:
                shutil.copytree(src, newPath)
            except OSError as e:
                messagebox.showerror("粘贴失败", str(e))
                return "break"
        else:
            stem, suffix = src.stem, src.suffix
            newPath = dstDir / f"{stem} 副本{suffix}"
            n = 1
            while newPath.exists():
                newPath = dstDir / f"{stem} 副本{n}{suffix}"
                n += 1
            try:
                shutil.copy2(src, newPath)
            except OSError as e:
                messagebox.showerror("粘贴失败", str(e))
                return "break"
        self.refresh()
        self._status(f"已粘贴 {newPath.name}")
        return "break"

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
