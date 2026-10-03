import numpy as np                      # 导入 NumPy，用于数值计算（当前代码暂未直接使用，但引擎中常用于矩阵/顶点数据）
from OpenGL.GL import *                 # 导入 OpenGL 核心函数（glClear、glBegin、glVertex 等）
from OpenGL.GLU import *                # 导入 GLU 工具库（gluOrtho2D、gluPerspective 等）
from OpenGL.GLUT import *               # 导入 GLUT 工具库（窗口创建、事件循环、回调注册）


class Main(object):
    def __init__(self):
        # self.geometry = geometry
        glutInit()                                          # 初始化 GLUT 库，必须在其他 glut 调用之前执行
        glutInitDisplayMode(GLUT_SINGLE | GLUT_RGBA)        # 设置显示模式：单缓冲 + RGBA 颜色
        glutInitWindowSize(400, 400)                        # 设置窗口初始大小为 400x400 像素
        glutCreateWindow(b"Hello OpenGL")                   # 创建窗口，标题为 "Hello OpenGL"（必须是 bytes）
        glutDisplayFunc(self.draw_geometry)                 # 注册渲染回调：每次窗口需要重绘时调用 draw_geometry
        self.init_condition()                               # 设置背景色和投影范围
        glutMainLoop()                                      # 进入 GLUT 事件循环，程序阻塞在此，直到窗口关闭

    def init_condition(self):
        glClearColor(1.0, 1.0, 1.0, 1.0)                    # 设置背景清除色为白色（R,G,B,A）
        gluOrtho2D(-8.0, 8.0, -8.0, 8.0)                    # 设置正交投影：x 范围 [-8,8]，y 范围 [-8,8]

    def render(self):
        pass                                                # 预留的渲染方法，当前未使用

    def draw_geometry(self):
        glClear(GL_COLOR_BUFFER_BIT)                        # 用 glClearColor 设置的颜色清除颜色缓冲
        glColor3f(1.0, 0.0, 0.0)                            # 设置当前绘制颜色为红色（R,G,B）
        glBegin(GL_QUADS)                                   # 开始绘制四边形，后续 4 个顶点组成一个四边形
        glVertex2f(0,0)                                   # 第 1 个顶点：(x=-2, y=2)
        glVertex2f(-2, 5)                                   # 第 2 个顶点：(x=-2, y=5)
        glVertex2f(-5, 5)                                   # 第 3 个顶点：(x=-5, y=5)
        glVertex2f(-5, 2)                                   # 第 4 个顶点：(x=-5, y=2)
        glEnd()                                             # 结束绘制，提交所有顶点数据
        glFlush()                                           # 强制刷新，确保绘制命令立即执行（单缓冲模式下需要）


if __name__ == "__main__":
    Main()                                                  # 实例化 Main，启动整个 OpenGL 程序