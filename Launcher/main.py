# -*- coding: utf-8 -*-
"""Vortex 启动器 —— 创建 / 打开游戏项目（类似 Unity Hub / UE Launcher）。

V1 功能：
- 创建项目：生成模板目录（Resources/、Engine/）、复制引擎图标、写 engineData.ved 元数据
- 项目注册表：Launcher/projects.json（名称 / 路径 / 创建时间 / 最近打开）
- 自动识别：刷新时扫描登记过的目录，凡含 Engine/engineData.ved 的目录都识别为 Vortex 项目
  （复制 / 移动过的项目点「刷新」即自动出现；「添加目录…」可把新位置纳入扫描）
- 项目列表：双击打开、选中后「打开 / 移除」按钮
- 打开项目：子进程拉起编辑器（Editor/main.py --project <路径>，cwd=引擎根）
- 自检模式：python Launcher/main.py --selftest（无窗口自动增删临时项目后退出）

说明：项目逻辑（createProject / registerProject / removeProject 等）与 GUI 分离，
编辑器尚未实现（V2）时「打开」会给出友好提示，不报错。
"""

import json
import shutil
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# ---- 路径与常量 ----
LAUNCHER_DIR = Path(__file__).resolve().parent
ENGINE_ROOT = LAUNCHER_DIR.parent          # Vortex 引擎根目录
REGISTRY_FILE = LAUNCHER_DIR / "projects.json"
ICON_FILE = ENGINE_ROOT / "engineIcon.png"         # 项目图标来源
EDITOR_ENTRY = ENGINE_ROOT / "Editor" / "main.py"  # 编辑器入口（V2 实现）
ENGINE_VERSION = "0.1.0"
ENGINE_DATA_VERSION = 1


# ---------------- 项目逻辑（与 GUI 无关，供自检 / 后续复用） ----------------

def _now():
    """当前时间字符串，如 2026-10-03 22:10:00。"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _registryData():
    """读取注册表文件，返回 {"scanDirs": [...], "projects": [...]}；
    兼容旧版纯列表格式（整个文件就是一个项目列表）。"""
    if not REGISTRY_FILE.exists():
        return {"scanDirs": [], "projects": []}
    try:
        data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"scanDirs": [], "projects": []}
    if isinstance(data, dict):
        projects = data.get("projects", [])
        return {
            "scanDirs": data.get("scanDirs", []) if isinstance(data.get("scanDirs"), list) else [],
            "projects": projects if isinstance(projects, list) else [],
        }
    if isinstance(data, list):  # 旧格式：整个文件就是项目列表
        return {"scanDirs": [], "projects": data}
    return {"scanDirs": [], "projects": []}


def _loadRegistry():
    """读取项目注册表（项目列表部分）；文件缺失或损坏时返回空列表。"""
    return _registryData()["projects"]


def _getScanDirs():
    """读取扫描目录列表（刷新时自动识别项目用）。"""
    return _registryData()["scanDirs"]


def _addScanDir(dirPath):
    """把目录加入扫描列表（按路径去重，持久化）。"""
    data = _registryData()
    target = Path(dirPath).resolve()
    existing = set(str(Path(d).resolve()) for d in data["scanDirs"])
    if str(target) in existing:
        return False
    data["scanDirs"].append(str(target))
    REGISTRY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def _saveRegistry(items):
    """保存项目注册表（保留扫描目录，按最近打开时间倒序）。"""
    data = _registryData()
    items.sort(key=lambda it: it.get("lastOpened", ""), reverse=True)
    data["projects"] = items
    REGISTRY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def createProject(name, path):
    """在 path 下创建项目模板，并写入注册表，返回项目信息 dict。

    模板结构：
        <path>/
        ├── Resources/               # 项目资源目录（模型 / 贴图 / 脚本）
        ├── Engine/
        │   └── engineData.ved       # 引擎元数据（JSON 简单版）
        └── engineIcon.png           # 引擎图标（自 Vortex 根复制）
    """
    root = Path(path)
    root.mkdir(parents=True, exist_ok=True)
    (root / "Resources").mkdir(exist_ok=True)
    (root / "Engine").mkdir(exist_ok=True)
    if ICON_FILE.exists():
        try:
            shutil.copy2(ICON_FILE, root / "engineIcon.png")
        except OSError:
            pass  # 图标复制失败不阻塞创建
    meta = {
        "name": name,
        "engineVersion": ENGINE_VERSION,
        "formatVersion": ENGINE_DATA_VERSION,
        "created": _now(),
    }
    (root / "Engine" / "engineData.ved").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    info = {"name": name, "path": str(root.resolve()), "created": _now(), "lastOpened": ""}
    registerProject(info)
    _addScanDir(str(root.parent))  # 自动把父目录纳入扫描，日后复制项目也能被识别
    return info


def registerProject(info):
    """注册 / 更新项目（按路径去重，同路径只保留一条）。
    返回 True 表示新增，False 表示已存在仅更新。"""
    items = _loadRegistry()
    target = Path(info["path"]).resolve()
    for it in items:
        if Path(it["path"]).resolve() == target:
            it.update(info)  # 更新名称 / 时间等字段
            _saveRegistry(items)
            return False
    items.append(info)
    _saveRegistry(items)
    return True


def removeProject(path):
    """从注册表移除项目（只删记录，不删磁盘文件）。"""
    target = Path(path).resolve()
    items = _loadRegistry()
    keep = [it for it in items if Path(it["path"]).resolve() != target]
    if len(keep) != len(items):
        _saveRegistry(keep)
        return True
    return False


def touchOpened(path):
    """记录最近打开时间，并刷新排序。"""
    target = Path(path).resolve()
    items = _loadRegistry()
    for it in items:
        if Path(it["path"]).resolve() == target:
            it["lastOpened"] = _now()
    _saveRegistry(items)


def _projectInfoFromDir(projectDir):
    """从项目目录生成注册条目：名称优先取 engineData.ved 里的 name，缺省用目录名；
    已在册的保留最近打开时间。"""
    vedPath = projectDir / "Engine" / "engineData.ved"
    name = projectDir.name
    created = ""
    try:
        meta = json.loads(vedPath.read_text(encoding="utf-8"))
        name = str(meta.get("name") or name)
        created = str(meta.get("created") or "")
    except (json.JSONDecodeError, OSError):
        pass
    info = {"name": name, "path": str(projectDir.resolve()), "created": created, "lastOpened": ""}
    for it in _loadRegistry():
        if Path(it["path"]).resolve() == Path(info["path"]).resolve():
            info["lastOpened"] = it.get("lastOpened", "")
            break
    return info


def scanForProjects():
    """自动识别 Vortex 项目：扫描所有扫描目录的直接子目录，
    把含 Engine/engineData.ved 标志的目录注册进列表。
    扫描前先把「已注册项目的父目录」补进扫描列表（兼容旧版无扫描列表的注册表）。
    返回本次新发现（新增）的条目列表，供 UI 提示。"""
    # 回填：保证已登记项目的父目录必在扫描列表里（老数据 / 移动过的项目也能被发现）
    parents = sorted({str(Path(it["path"]).resolve().parent) for it in _loadRegistry() if it.get("path")})
    for p in parents:
        _addScanDir(p)
    newFound = []
    for dirPath in _getScanDirs():
        root = Path(dirPath)
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if (child / "Engine" / "engineData.ved").is_file():
                info = _projectInfoFromDir(child)
                if registerProject(info):
                    newFound.append(info)
    return newFound


def isVortexProject(path):
    """判断一个目录是否为有效的 Vortex 项目（含 Engine/engineData.ved）。"""
    return (Path(path) / "Engine" / "engineData.ved").is_file()


def launchEditor(projectPath):
    """子进程启动编辑器。返回是否成功拉起。"""
    if not EDITOR_ENTRY.exists():
        return False
    try:
        subprocess.Popen(
            [sys.executable, str(EDITOR_ENTRY), "--project", str(projectPath)],
            cwd=str(ENGINE_ROOT),
        )
        return True
    except OSError:
        return False


# ---------------- 启动器界面 ----------------

class LauncherApp:
    """主窗口：项目列表 + 创建 / 打开 / 移除。"""

    def __init__(self, root):
        self.root = root
        root.title("Vortex 启动器")
        root.geometry("720x480")
        root.minsize(560, 360)
        self._buildUI()
        self.refreshList()

    # ---- UI 搭建 ----
    def _buildUI(self):
        top = ttk.Frame(self.root, padding=(12, 10))
        top.pack(fill=tk.X)
        ttk.Label(top, text="Vortex 启动器", font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)
        ttk.Label(top, text="创建 / 打开游戏项目").pack(side=tk.LEFT, padx=(10, 0))

        # 项目列表
        body = ttk.Frame(self.root, padding=(12, 4))
        body.pack(fill=tk.BOTH, expand=True)
        cols = ("name", "path", "last")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("name", text="项目名称")
        self.tree.heading("path", text="路径")
        self.tree.heading("last", text="最近打开")
        self.tree.column("name", width=140, anchor=tk.W)
        self.tree.column("path", width=360, anchor=tk.W)
        self.tree.column("last", width=150, anchor=tk.W)
        vbar = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<Double-1>", lambda e: self.openSelected())

        # 按钮栏
        bar = ttk.Frame(self.root, padding=(12, 8))
        bar.pack(fill=tk.X)
        ttk.Button(bar, text="创建项目", command=self.createProjectDialog).pack(side=tk.LEFT)
        ttk.Button(bar, text="打开", command=self.openSelected).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(bar, text="移除", command=self.removeSelected).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(bar, text="添加目录…", command=self.addScanDirDialog).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(bar, text="刷新", command=self.refreshList).pack(side=tk.RIGHT)

    # ---- 列表 ----
    def refreshList(self, scan=True):
        """重绘项目列表；scan=True 时先自动扫描磁盘识别新项目（「刷新」按钮语义）。"""
        if scan:
            scanForProjects()
        self.tree.delete(*self.tree.get_children())
        for it in _loadRegistry():
            self.tree.insert("", tk.END, values=(it["name"], it["path"], it.get("lastOpened", "")))

    def addScanDirDialog(self):
        """选择目录加入扫描列表，并在其中自动识别项目。"""
        d = filedialog.askdirectory(parent=self.root, title="选择目录（将扫描其中所有 Vortex 项目）")
        if not d:
            return
        _addScanDir(d)
        newFound = scanForProjects()
        self.refreshList(scan=False)
        if newFound:
            messagebox.showinfo("添加目录", f"在该目录发现 {len(newFound)} 个项目，已加入列表。")
        else:
            messagebox.showinfo("添加目录", "该目录下未发现新的 Vortex 项目。")

    def _selectedProject(self):
        """返回当前选中的注册表条目，未选中返回 None。"""
        sel = self.tree.selection()
        if not sel:
            return None
        index = self.tree.index(sel[0])
        items = _loadRegistry()
        return items[index] if 0 <= index < len(items) else None

    # ---- 操作 ----
    def openSelected(self):
        info = self._selectedProject()
        if not info:
            messagebox.showinfo("Vortex 启动器", "请先在列表中选择一个项目。")
            return
        path = info["path"]
        if not Path(path).is_dir():
            messagebox.showerror("Vortex 启动器", f"项目目录不存在：\n{path}\n您可以从列表中移除该项目。")
            return
        if not isVortexProject(path):
            messagebox.showerror("Vortex 启动器", f"「{path}」不是有效的 Vortex 项目（缺少 Engine/engineData.ved）。")
            return
        touchOpened(path)
        self.refreshList()
        if launchEditor(path):
            self.root.iconify()  # 编辑器启动后最小化启动器
        else:
            messagebox.showinfo(
                "Vortex 启动器",
                "编辑器尚未就绪（V2 开发中）。\n本版本已完成项目创建与管理，下个阶段将实现编辑器并自动从这里启动。",
            )

    def removeSelected(self):
        info = self._selectedProject()
        if not info:
            messagebox.showinfo("Vortex 启动器", "请先在列表中选择一个项目。")
            return
        ok = messagebox.askyesno(
            "移除项目",
            f"只从列表移除「{info['name']}」？\n磁盘上的项目文件不会删除。",
        )
        if ok:
            removeProject(info["path"])
            self.refreshList()

    # ---- 创建项目对话框 ----
    def createProjectDialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("创建项目")
        dlg.geometry("460x190")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)

        ttk.Label(dlg, text="项目名称：").grid(row=0, column=0, padx=16, pady=(18, 6), sticky=tk.W)
        nameVar = tk.StringVar(value="MyGame")
        ttk.Entry(dlg, textvariable=nameVar, width=36).grid(row=0, column=1, padx=(0, 16), pady=(18, 6))

        ttk.Label(dlg, text="存放目录：").grid(row=1, column=0, padx=16, pady=6, sticky=tk.W)
        pathVar = tk.StringVar()
        ttk.Entry(dlg, textvariable=pathVar, width=28).grid(row=1, column=1, pady=6, sticky=tk.W)

        def browse():
            d = filedialog.askdirectory(parent=dlg, title="选择项目存放目录")
            if d:
                base = Path(d)
                # 默认在所选目录下新建「项目名」子目录，避免污染父目录
                pathVar.set(str(base / nameVar.get().strip()))

        ttk.Button(dlg, text="浏览…", command=browse).grid(row=1, column=1, padx=(250, 16), pady=6, sticky=tk.W)

        hint = ttk.Label(dlg, text="将在所选目录创建：Resources / Engine / engineData.ved", foreground="#666")
        hint.grid(row=2, column=0, columnspan=2, padx=16, pady=(6, 4), sticky=tk.W)

        def doCreate():
            name = nameVar.get().strip()
            target = pathVar.get().strip()
            if not name:
                messagebox.showwarning("创建项目", "请输入项目名称。", parent=dlg)
                return
            if not target:
                messagebox.showwarning("创建项目", "请选择项目存放目录。", parent=dlg)
                return
            root = Path(target)
            if (root / "Engine" / "engineData.ved").exists():
                if not messagebox.askyesno("创建项目", "该目录已包含 Vortex 项目，是否覆盖注册信息？", parent=dlg):
                    return
            try:
                info = createProject(name, target)
            except OSError as e:
                messagebox.showerror("创建项目", f"创建失败：{e}", parent=dlg)
                return
            dlg.destroy()
            messagebox.showinfo("创建项目", f"项目「{name}」创建成功：\n{info['path']}")
            self.refreshList()
            # 询问是否立即打开编辑器
            if messagebox.askyesno("Vortex 启动器", "是否立即打开编辑器？"):
                self._openPath(info["path"])

        def doCancel():
            dlg.destroy()

        btns = ttk.Frame(dlg)
        btns.grid(row=3, column=0, columnspan=2, pady=(12, 14))
        ttk.Button(btns, text="创建", command=doCreate).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btns, text="取消", command=doCancel).pack(side=tk.LEFT)

    def _openPath(self, path):
        """通用打开流程：记录时间 → 列表刷新 → 拉起编辑器。"""
        touchOpened(path)
        self.refreshList()
        if launchEditor(path):
            self.root.iconify()
        else:
            messagebox.showinfo(
                "Vortex 启动器",
                "编辑器尚未就绪（V2 开发中）。\n本版本已完成项目创建与管理，下个阶段将实现编辑器并自动从这里启动。",
            )


# ---------------- 自检模式 ----------------

def selftest():
    """无窗口自检：创建/复制项目 → 校验模板、注册表增删、磁盘自动识别 → 清理。

    使用临时注册表，不污染真实数据。"""
    import shutil as _shutil
    import tempfile

    print("[自检] 开始…")
    tmpRoot = Path(tempfile.mkdtemp(prefix="vortex_selftest_"))
    try:
        # 使用临时注册表文件（隔离真实数据）
        global REGISTRY_FILE
        REGISTRY_FILE = tmpRoot / "projects.json"

        # 1. 创建项目模板
        projDir = tmpRoot / "自检项目"
        info = createProject("自检项目", str(projDir))
        assert projDir.is_dir(), "项目目录未创建"
        assert (projDir / "Resources").is_dir(), "Resources 目录未创建"
        assert (projDir / "Engine").is_dir(), "Engine 目录未创建"
        assert (projDir / "Engine" / "engineData.ved").exists(), "engineData.ved 未写入"
        assert (projDir / "engineIcon.png").exists(), "引擎图标未复制"
        assert info["name"] == "自检项目"
        assert any(Path(i["path"]).resolve() == projDir.resolve() for i in _loadRegistry()), "注册表未收录"
        assert _getScanDirs(), "创建项目后父目录应自动加入扫描列表"

        # 2. 模拟用户复制项目 → 点「刷新」应自动识别新项目
        copyDir = tmpRoot / "自检项目-副本"
        _shutil.copytree(projDir, copyDir)
        newFound = scanForProjects()
        assert any(Path(p["path"]).resolve() == copyDir.resolve() for p in newFound), "复制出的项目未被识别"
        assert sum(1 for i in _loadRegistry()
                   if Path(i["path"]).resolve() == copyDir.resolve()) == 1, "识别出的项目应只有一条记录"

        # 3. 重复注册不产生重复项（按路径去重）
        registerProject(info)
        assert sum(1 for i in _loadRegistry() if Path(i["path"]).resolve() == projDir.resolve()) == 1, "去重失败"

        # 4. 最近打开时间记录
        touchOpened(str(projDir))
        entries = [i for i in _loadRegistry() if Path(i["path"]).resolve() == projDir.resolve()]
        assert entries and entries[0]["lastOpened"], "最近打开时间未记录"

        # 5. 项目有效性判断
        assert isVortexProject(str(projDir)), "应识别为 Vortex 项目"
        assert not isVortexProject(str(tmpRoot)), "无 ved 标志的目录不应被识别"

        # 6. 移除（只删注册，不删磁盘）
        assert removeProject(str(copyDir)), "移除失败"
        assert not any(Path(i["path"]).resolve() == copyDir.resolve() for i in _loadRegistry()), "注册表仍有残留"
        assert copyDir.exists(), "不应删除磁盘文件"

        # 7. 旧版注册表（纯列表、无 scanDirs）→ 扫描回填父目录后仍能自动识别
        data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        REGISTRY_FILE.write_text(json.dumps(data["projects"], ensure_ascii=False, indent=2), encoding="utf-8")
        newFound = scanForProjects()
        assert any(Path(p["path"]).resolve() == copyDir.resolve() for p in newFound), "旧注册表回填后未能识别"

        print("[自检] 通过：模板创建 / 自动识别复制项目 / 注册表增删去重 / 最近打开 / 旧数据回填 均正常")
        return 0
    except AssertionError as e:
        print(f"[自检] 失败：{e}")
        return 1
    finally:
        _shutil.rmtree(tmpRoot, ignore_errors=True)


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()