# -*- coding: utf-8 -*-
"""项目面板 —— 资源浏览器：浏览 / 创建 / 导入 / 双击打开 / 拖拽 / 复制项目内所有资源。

资源类型（V5）：
- .obj 模型（导入 / 双击 = 使用：换网格或建物体）
- .vmat 材质（创建 / 单击或双击 = 在检查器编辑颜色）
- .vscene 场景（创建 / 双击 = 打开场景；新建场景默认含主相机 + 方向光）
- .vpy 脚本（创建 / 挂到物体脚本组件，播放模式执行）

交互：
- 右键：新建文件夹 / 创建场景 / 创建材质 / 创建脚本 / 导入模型 / 刷新 / 重命名 / 删除
- 创建与导入都落在「当前选中目录」（不自动建子文件夹，完全自由）
- 拖拽资源/文件夹到另一目录 = 移动
- Ctrl+C / Ctrl+V：复制资源（文件或整目录）到当前目录
- Ctrl+X / Ctrl+V：剪切资源 = 移动到当前目录
- Delete：删除选中资源（Ctrl+Z 可撤销）
- Ctrl+Z：撤销资源操作（创建/删除/重命名/移动/复制粘贴）
"""

import shutil
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import numpy as np

from ..core.materialCache import createMaterialFile
from ..core.meshCache import importModel
from ..core.scene import Camera, GameObject, Light, Scene
from ..core.serializer import saveSceneFile

# .vpy 脚本模板（播放模式：进入时 start()，之后每帧 update()）
SCRIPT_TEMPLATE = """# -*- coding: utf-8 -*-
# Vortex 物体脚本
# 进入播放调用 start()；播放期间每帧调用 update()
# 在脚本里获取当前物体与帧间隔：
#   obj = getSelf()
#   dt = getDuration()
# 更多 API（创建/删除物体、材质、文件、窗口等）见「帮助 → 脚本 API 参考」

def start():
    obj = getSelf()
    pass

def update():
    obj = getSelf()
    dt = getDuration()
    # 示例：每秒绕 Y 轴旋转 30 度
    # obj.transform.rotation[1] += 30 * dt
    pass
"""


class ProjectPanel(tk.Frame):
    """项目 Resources 资源浏览器。"""

    def __init__(self, master, projectRoot=None, onOpenScene=None,
                 onUseMesh=None, onEditMaterial=None, onImport=None,
                 onOpenScript=None, onStatus=None, **kw):
        super().__init__(master, **kw)
        self.projectRoot = Path(projectRoot) if projectRoot else None
        self.onOpenScene = onOpenScene      # 双击 .vscene：打开场景
        self.onUseMesh = onUseMesh          # 双击 .obj：使用该模型
        self.onEditMaterial = onEditMaterial  # 选中/双击 .vmat：检查器编辑材质
        self.onImport = onImport            # 导入模型完成回调（刷新检查器网格下拉）
        self.onOpenScript = onOpenScript    # 双击 .vpy：打开内置代码编辑器
        self.onStatus = onStatus            # 状态栏消息回调
        self._clipboard = None              # Ctrl+C/X 剪切源（Path）
        self._cutMode = False               # True=剪切（粘贴=移动）
        self._undoStack = []                # 资源操作撤销栈 [(undo_fn, 描述)]
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
        self.tree.bind("<Control-x>", self._onCut)
        self.tree.bind("<Control-z>", self._undo)
        self.tree.bind("<Delete>", self._deletePath)   # 焦点在资源树时 Delete 删资源
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
    def _pathFromItem(self, item):
        """tree item → 完整路径（文件或目录）。root 节点（项目名）是虚拟节点，
        不代表真实目录；树结构为 root → Resources 内容（Resources 无独立节点），
        目录路径 = 项目根/Resources/…（拼链时跳过 root 的项目名）。"""
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
        # 去掉 root 的项目名节点
        if chain and chain[0] == self.projectRoot.name:
            chain.pop(0)
        path = self.projectRoot / "Resources"
        for part in chain:
            path = path / part
        return path

    def _selectedPath(self):
        """当前选中项（文件或目录）的完整路径；无选中返回 None。"""
        sel = self.tree.selection()
        if not sel:
            return None
        return self._pathFromItem(sel[0])

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
        menu.add_command(label="创建脚本…", command=self._createScript)
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
        self._pushUndo(lambda: self._undoRemovePath(target), f"新建文件夹 {name}")
        self.refresh()
        self._status(f"已创建文件夹 {name}")

    def _createScene(self):
        """在「当前目录」创建 .vscene 场景文件（默认含主相机 + 方向光）。"""
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
        saveSceneFile(self._defaultScene(), path)
        self._pushUndo(lambda: self._unlinkQuiet(path), f"创建场景 {path.name}")
        self.refresh()
        self._status(f"已创建场景 {path.stem}.vscene")

    @staticmethod
    def _defaultScene():
        """新建场景的默认内容：主相机 + 方向光（不再是空场景「空气」）。"""
        s = Scene()
        cam = GameObject(name="主相机")
        cam.addComponent(Camera())
        cam.transform.position = np.array([0.0, 2.0, 6.0])
        sun = GameObject(name="方向光")
        sun.addComponent(Light(lightType="directional",
                               color=(1.0, 1.0, 0.95), intensity=1.0))
        sun.transform.rotation = np.array([45.0, -30.0, 0.0])
        s.addObject(cam)
        s.addObject(sun)
        return s

    def _createMaterial(self):
        """在「当前目录」创建 .vmat 材质文件。"""
        if self.projectRoot is None:
            messagebox.showinfo("项目", "当前没有打开项目，无法创建材质。")
            return
        name = simpledialog.askstring("创建材质", "材质名称：", initialvalue="新材质")
        if not name:
            return
        targetDir = self._currentDir()
        rel = createMaterialFile(self.projectRoot, name=name,
                                 subdir=self._subdirOf(targetDir))
        self._pushUndo(lambda: self._unlinkQuiet(targetDir / f"{name}.vmat"),
                       f"创建材质 {name}")
        self.refresh()
        self._status(f"已创建材质 {rel}")

    def _createScript(self):
        """在「当前目录」创建 .vpy 脚本文件（播放模式执行）。"""
        if self.projectRoot is None:
            messagebox.showinfo("项目", "当前没有打开项目，无法创建脚本。")
            return
        name = simpledialog.askstring("创建脚本", "脚本名称：", initialvalue="新脚本")
        if not name:
            return
        targetDir = self._currentDir()
        path = targetDir / f"{name}.vpy"
        n = 1
        while path.exists():
            path = targetDir / f"{name}{n}.vpy"
            n += 1
        try:
            path.write_text(SCRIPT_TEMPLATE, encoding="utf-8")
        except OSError as e:
            messagebox.showerror("创建脚本", str(e))
            return
        self._pushUndo(lambda: self._unlinkQuiet(path), f"创建脚本 {path.name}")
        self.refresh()
        self._status(f"已创建脚本 {path.name}（挂到物体的脚本组件即可）")

    def _importModel(self):
        """导入 .obj 模型到「当前目录」（外部文件用系统选择器是唯一途径）。"""
        if self.projectRoot is None:
            messagebox.showinfo("项目", "当前没有打开项目，无法导入资源。")
            return
        file = filedialog.askopenfilename(
            title="导入 .obj 模型", filetypes=[("OBJ 模型", "*.obj"), ("所有文件", "*.*")])
        if not file:
            return
        targetDir = self._currentDir()
        try:
            rel = importModel(Path(file), self.projectRoot,
                              subdir=self._subdirOf(targetDir))
        except (OSError, ValueError) as e:
            messagebox.showerror("导入失败", str(e))
            return
        self._pushUndo(lambda: self._unlinkQuiet(targetDir / Path(rel).name),
                       f"导入模型 {Path(rel).name}")
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
        oldPath = path
        self._pushUndo(lambda: self._restorePath(target, oldPath),
                       f"重命名 {oldPath.name} → {newName}")
        self.refresh()
        self._status(f"已重命名 {path.name} → {newName}")

    def _deletePath(self, _event=None):
        """删除选中资源（移到临时区，Ctrl+Z 可撤销恢复）。"""
        path = self._selectedPath()
        if path is None or not path.exists():
            return "break" if _event is not None else None
        kind = "文件夹" if path.is_dir() else "文件"
        if not messagebox.askyesno("删除", f"确定删除{kind}「{path.name}」？\n可 Ctrl+Z 撤销。"):
            return "break" if _event is not None else None
        try:
            trashDir = Path(tempfile.mkdtemp(prefix="vortex_undo_"))
            target = trashDir / path.name
            path.rename(target)
        except OSError as e:
            messagebox.showerror("删除", str(e))
            return "break" if _event is not None else None
        origPath = path
        self._pushUndo(lambda: self._restorePath(target, origPath),
                       f"删除 {path.name}")
        self.refresh()
        self._status(f"已删除 {path.name}（Ctrl+Z 可撤销）")
        return "break" if _event is not None else None

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
            return None
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
            return None
        self._pushUndo(lambda: self._restorePath(target, src), f"移动 {src.name}")
        self.refresh()
        self._status(f"已移动 {src.name}")
        return target

    def _treePath(self, item):
        """tree item → 完整路径（文件或目录）。"""
        return self._pathFromItem(item)

    # ---- 复制 / 剪切 / 粘贴 ----
    def _onCopy(self, _event):
        path = self._selectedPath()
        if path is None or not path.exists():
            return "break"
        self._clipboard = path
        self._cutMode = False
        self._status(f"已复制 {path.name}")
        return "break"

    def _onCut(self, _event):
        """Ctrl+X：剪切选中资源（粘贴=移动）。"""
        path = self._selectedPath()
        if path is None or not path.exists():
            return "break"
        self._clipboard = path
        self._cutMode = True
        self._status(f"已剪切 {path.name}（Ctrl+V 粘贴 = 移动）")
        return "break"

    def _onPaste(self, _event):
        if self._clipboard is None or not self._clipboard.exists():
            self._status("剪贴板没有资源")
            return "break"
        dstDir = self._currentDir()
        src = self._clipboard
        if self._cutMode:
            # 剪切粘贴 = 移动（_movePath 已记录撤销）
            moved = self._movePath(src, dstDir)
            self._cutMode = False
            self._clipboard = None
            if moved is not None:
                self._status(f"已移动 {moved.name}")
            return "break"
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
        self._pushUndo(lambda: self._undoRemovePath(newPath), f"复制粘贴 {newPath.name}")
        self.refresh()
        self._status(f"已粘贴 {newPath.name}")
        return "break"

    # ---- 撤销（资源操作逆操作栈） ----
    def _pushUndo(self, undo, desc):
        self._undoStack.append((undo, desc))
        if len(self._undoStack) > 30:
            self._undoStack.pop(0)

    def _undo(self, _event=None):
        if not self._undoStack:
            self._status("没有可撤销的资源操作")
            return "break"
        undo, desc = self._undoStack.pop()
        try:
            undo()
        except OSError as e:
            messagebox.showerror("撤销失败", str(e))
        self.refresh()
        self._status(f"已撤销：{desc}")
        return "break"

    def _restorePath(self, src, origPath):
        """把临时区的资源移回原路径（原路径被占用则自动加「恢复N」）。"""
        if origPath.exists():
            parent = origPath.parent
            n = 1
            while True:
                cand = parent / f"{origPath.stem} 恢复{n}{origPath.suffix}"
                if not cand.exists():
                    origPath = cand
                    break
                n += 1
        src.rename(origPath)

    def _undoRemovePath(self, path):
        """撤销粘贴/创建：把刚新建的资源移到临时区（即删除）。"""
        try:
            trashDir = Path(tempfile.mkdtemp(prefix="vortex_undo_"))
            path.rename(trashDir / path.name)
        except OSError:
            self._unlinkQuiet(path)

    def _unlinkQuiet(self, path):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError:
            pass

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
        elif suffix == ".vpy" and self.onOpenScript:
            self.onOpenScript(path)

    def _status(self, msg):
        if self.onStatus:
            try:
                self.onStatus(msg)
            except Exception:
                pass
