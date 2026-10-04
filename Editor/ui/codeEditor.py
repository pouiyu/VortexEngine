# -*- coding: utf-8 -*-
"""引擎内置代码编辑器（V5.2）：编辑 .vpy 脚本，带语法高亮。

- 双击项目资源里的 .vpy 自动打开
- 语法高亮：注释（灰斜体）/ 关键字（蓝）/ 字符串（绿）/ 数字（橙）
- Ctrl+S 保存（UTF-8），标题星号提示未保存，关闭时询问
- Ctrl+Z 撤销 / Ctrl+A 全选 / Ctrl+F 查找跳转（基础）
"""

import re
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

FONT = ("Consolas", 11)

# tag 配置顺序即显示优先级（后配置的在上）：注释 > 关键字 > 字符串 > 数字
_TAG_STYLES = [
    ("number", "#d69c56"),      # 数字：橙
    ("string", "#6bbf6b"),      # 字符串：绿
    ("keyword", "#5fa8e0"),     # 关键字：蓝
    ("comment", "#8a8a96"),     # 注释：灰（最后配置 → 优先级最高，覆盖其它）
]

_KEYWORDS = (
    "def return import from if elif else for while class break continue pass "
    "True False None and or not in is with as try except raise lambda global "
    "nonlocal yield assert del self"
)

_RE_COMMENT = re.compile(r"#[^\n]*")
_RE_STRING = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'")
_RE_KEYWORD = re.compile(r"\b(" + _KEYWORDS.replace(" ", "|") + r")\b")
_RE_NUMBER = re.compile(r"\b\d+(\.\d+)?\b")


class CodeEditorWindow(tk.Toplevel):
    """单个 .vpy 文件的代码编辑器窗口。"""

    def __init__(self, master, path, onClosed=None):
        super().__init__(master)
        self.path = Path(path)
        self.onClosed = onClosed
        self._dirty = False
        self._closeRequested = False

        self.title(f"脚本：{self.path.name}")
        self.geometry("760x520")
        self.minsize(420, 260)

        # 编辑区
        self.editor = tk.Text(self, font=FONT, wrap="none", undo=True,
                              background="#1e1e28", foreground="#d8d8e0",
                              insertbackground="#ffffff", selectbackground="#3d5a80",
                              relief=tk.FLAT, padx=8, pady=6)
        self.editor.pack(fill=tk.BOTH, expand=True)

        # 滚动条
        sb = tk.Scrollbar(self, orient=tk.VERTICAL, command=self.editor.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.editor.config(yscrollcommand=sb.set)

        # 底部状态栏：保存提示 + 光标位置
        self.status = tk.Label(self, text="", anchor=tk.W,
                               background="#26262f", foreground="#9a9aa8", padx=8)
        self.status.pack(fill=tk.X, side=tk.BOTTOM)

        # 语法高亮 tag（配置顺序即优先级）
        for name, color in _TAG_STYLES:
            if name == "comment":
                self.editor.tag_configure(name, foreground=color, font=(FONT[0], FONT[1], "italic"))
            else:
                self.editor.tag_configure(name, foreground=color)

        # 载入文件
        try:
            self.editor.insert("1.0", self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as e:
            self.editor.insert("1.0", f"# 读取失败：{e}\n")
        self.editor.edit_modified(False)
        self.editor.edit_reset()          # 清掉载入时的 undo 记录
        self._rehighlight()

        # 事件
        self.editor.bind("<KeyRelease>", self._onKey)
        self.editor.bind("<Control-s>", self.save)
        self.editor.bind("<Control-a>", self._selectAll)
        self.editor.bind("<Control-f>", self._find)
        self.editor.bind("<Escape>", lambda e: self._findBar.pack_forget() if hasattr(self, "_findBar") else None)
        self.editor.tag_bind("string", "<Double-1>", lambda e: "break")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._updateTitle()
        self.editor.focus_set()

    # ---- 保存 ----
    def save(self, _event=None):
        """写回 .vpy（UTF-8），清除未保存标记。"""
        try:
            self.path.write_text(self.editor.get("1.0", "end-1c"), encoding="utf-8")
        except OSError as e:
            messagebox.showerror("保存失败", str(e), parent=self)
            return "break"
        self.editor.edit_modified(False)
        self._dirty = False
        self._updateTitle()
        self.status.config(text=f"已保存 {self.path.name}  （Ctrl+S）")
        return "break"

    # ---- 未保存跟踪 ----
    def _onKey(self, event):
        if self.editor.edit_modified():
            self.editor.edit_modified(False)
            if not self._dirty:
                self._dirty = True
                self._updateTitle()
        self._scheduleHighlight()
        self._updatePos()

    def _updateTitle(self):
        star = " *" if self._dirty else ""
        self.title(f"脚本：{self.path.name}{star}")

    def _updatePos(self):
        try:
            line, col = self.editor.index("insert").split(".")
            self.status.config(text=f"行 {int(line)}，列 {int(col) + 1}")
        except Exception:
            pass

    # ---- 语法高亮 ----
    def _scheduleHighlight(self):
        if hasattr(self, "_hlAfter"):
            self.after_cancel(self._hlAfter)
        self._hlAfter = self.after(120, self._rehighlight)

    def _rehighlight(self):
        """全文重扫并打 tag（tag 不影响内容/撤销）。"""
        text = self.editor
        content = text.get("1.0", "end-1c")
        for name, _color in _TAG_STYLES:
            text.tag_remove(name, "1.0", "end")

        def add(regex, tag):
            for m in regex.finditer(content):
                try:
                    start = text.index(f"1.0 + {m.start()}c")
                    end = text.index(f"1.0 + {m.end()}c")
                    text.tag_add(tag, start, end)
                except tk.TclError:
                    return

        add(_RE_NUMBER, "number")
        add(_RE_STRING, "string")
        add(_RE_KEYWORD, "keyword")
        add(_RE_COMMENT, "comment")

    # ---- 辅助 ----
    def _selectAll(self, _event=None):
        self.editor.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _find(self, _event=None):
        if not hasattr(self, "_findBar"):
            bar = tk.Frame(self, background="#26262f")
            self._findEntry = tk.Entry(bar, width=22)
            self._findEntry.pack(side=tk.LEFT, padx=4, pady=2)
            tk.Button(bar, text="下一个", width=6,
                      command=self._findNext).pack(side=tk.LEFT, padx=2)
            bar.pack(fill=tk.X, side=tk.BOTTOM)
            self._findBar = bar
            self._findEntry.bind("<Return>", lambda e: self._findNext())
        self._findBar.pack(fill=tk.X, side=tk.BOTTOM)
        self._findEntry.focus_set()
        return "break"

    def _findNext(self):
        kw = self._findEntry.get()
        if not kw:
            return
        start = self.editor.index("insert")
        idx = self.editor.search(kw, start, stopindex="end", nocase=True)
        if not idx:
            idx = self.editor.search(kw, "1.0", stopindex="end", nocase=True)
        if idx:
            self.editor.tag_remove("sel", "1.0", "end")
            self.editor.tag_add("sel", idx, f"{idx}+{len(kw)}c")
            self.editor.mark_set("insert", idx)
            self.editor.see(idx)

    def _close(self):
        """关闭：未保存先询问（保存 / 不保存 / 取消）。"""
        if self._dirty:
            choice = messagebox.askyesnocancel(
                "未保存", f"「{self.path.name}」有未保存的修改，是否保存？",
                parent=self)
            if choice is None:
                return
            if choice:
                self.save()
        self._closeRequested = True
        self.destroy()
        if self.onClosed:
            self.onClosed()
