# -*- coding: utf-8 -*-
"""V5.6 物理系统：基于 pybullet（Bullet Physics）的 3D 刚体模拟。

设计：
- 播放时创建无头物理世界（pybullet DIRECT），每帧固定步长模拟
- 场景自动同步：有 Rigidbody + 至少一个 Collider 的物体自动建刚体；
  播放中脚本新增/删除物体也自动注册/注销（每帧 diff）
- 只处理没有父物体的根级物体（子物体随父刚体）
- 停止播放时断开连接，场景恢复播放前快照（编辑器快照机制不变）
"""

import numpy as np

from .scene import BoxCollider, Rigidbody, SphereCollider, worldMatrix

try:
    import pybullet as pb
    _PB_AVAILABLE = True
except Exception:
    pb = None
    _PB_AVAILABLE = False

_FIXED_STEP = 1.0 / 60.0   # 编辑器的"标称"物理步长（实际内部子步见 _SUB_STEP）
_SUB_STEP = 1.0 / 240.0    # pybullet 内部固定步长（stepSimulation 每步 1/240s）


class PhysicsWorld:
    """pybullet 无头物理世界（每场景播放周期一个实例）。"""

    def __init__(self):
        self.client = None
        self.bodies = {}        # pybullet body id → GameObject
        self.goToBody = {}      # GameObject.uuid → pybullet body id
        self._accum = 0.0
        self._running = False

    @property
    def available(self):
        return _PB_AVAILABLE

    # ---- 生命周期 ----
    def start(self, scene):
        """进入播放：创建物理世界并注册场景里所有物理物体。"""
        if not _PB_AVAILABLE:
            return False
        self.stop()
        self.client = pb.connect(pb.DIRECT)
        pb.setGravity(0.0, -9.8, 0.0, physicsClientId=self.client)
        pb.setTimeStep(_SUB_STEP, self.client)   # 内部步长 1/240s（显式声明）
        self._scene = scene
        self._running = True
        self._syncAll()
        return True

    def stop(self):
        """停止播放：清理。"""
        self._running = False
        self.bodies = {}
        self.goToBody = {}
        self._accum = 0.0
        self._scene = None
        if self.client is not None:
            try:
                pb.disconnect(self.client)
            except Exception:
                pass
            self.client = None

    # ---- 注册 / 注销 ----
    def _register(self, go):
        """为单个物体创建刚体并返回 body id（失败返回 None）。"""
        if go.parent is not None:
            return None  # 子物体不单独物理
        rb = go.getComponent(Rigidbody)
        if rb is None:
            return None
        colliders = [c for c in go.components
                     if isinstance(c, (BoxCollider, SphereCollider))]
        if not colliders:
            return None
        # 构建碰撞形状（多碰撞体取第一个为主体，其余尝试 compound）
        shapeInfos = []
        for c in colliders:
            if isinstance(c, BoxCollider):
                hw, hh, hd = [v * 0.5 for v in c.size]
                sid = pb.createCollisionShape(
                    pb.GEOM_BOX, halfExtents=[hw, hh, hd],
                    collisionFramePosition=c.offset, physicsClientId=self.client)
            else:
                sid = pb.createCollisionShape(
                    pb.GEOM_SPHERE, radius=c.radius,
                    collisionFramePosition=c.offset, physicsClientId=self.client)
            shapeInfos.append((sid, c))
        sids = [s for s, _ in shapeInfos]
        m = worldMatrix(go)
        pos = m[:3, 3]
        orient = pb.getQuaternionFromEuler(go.transform.rotation,
                                           physicsClientId=self.client)
        mass = 0.0 if (rb.isKinematic or rb.mass <= 0.0) else float(rb.mass)
        bodyId = pb.createMultiBody(baseMass=mass,
                                    baseCollisionShapeIndex=sids[0],
                                    basePosition=[float(v) for v in pos],
                                    baseOrientation=orient,
                                    physicsClientId=self.client)
        if len(sids) > 1:
            try:
                pb.setCollisionShapeList(bodyId, sids, physicsClientId=self.client)
            except Exception:
                for extra in sids[1:]:
                    try:
                        pb.removeBody(extra, physicsClientId=self.client)
                    except Exception:
                        pass
        # 物理参数：摩擦 / 弹性 / 重力
        for sid, c in shapeInfos:
            try:
                pb.changeDynamics(bodyId, -1, lateralFriction=c.friction,
                                  restitution=c.restitution,
                                  physicsClientId=self.client)
            except Exception:
                pass
        if not rb.useGravity:
            try:
                pb.changeDynamics(bodyId, -1, gravityFactor=0.0,
                                  physicsClientId=self.client)
            except Exception:
                pass
        self.bodies[bodyId] = go
        self.goToBody[go.uuid] = bodyId
        return bodyId

    def _unregister(self, go):
        bodyId = self.goToBody.pop(go.uuid, None)
        if bodyId is None:
            return
        self.bodies.pop(bodyId, None)
        try:
            pb.removeBody(bodyId, physicsClientId=self.client)
        except Exception:
            pass

    def _syncAll(self):
        """初次注册全部物理物体。"""
        if self._scene is None:
            return
        for go in self._scene.objects:
            if go.uuid not in self.goToBody:
                self._register(go)

    # ---- 每帧 ----
    def step(self, dt):
        """按固定步长推进物理并回写 Transform。"""
        if not self._running or self.client is None or self._scene is None:
            return
        # 场景增量同步：新增/删除
        uuids = {go.uuid for go in self._scene.objects}
        for uuid, bodyId in list(self.goToBody.items()):
            if uuid not in uuids:
                try:
                    pb.removeBody(bodyId, physicsClientId=self.client)
                except Exception:
                    pass
                self.bodies.pop(bodyId, None)
                self.goToBody.pop(uuid, None)
        for go in self._scene.objects:
            if go.uuid not in self.goToBody and go.active:
                self._register(go)
        # 运动学物体：每帧从 Transform 强制写回（由脚本/动画驱动）
        for uuid, bodyId in list(self.goToBody.items()):
            go = self.bodies.get(bodyId)
            if go is None:
                continue
            rb = go.getComponent(Rigidbody)
            if rb is not None and rb.isKinematic and go.active:
                m = worldMatrix(go)
                pos = m[:3, 3]
                orient = pb.getQuaternionFromEuler(go.transform.rotation,
                                                   physicsClientId=self.client)
                pb.resetBasePositionAndOrientation(
                    bodyId, [float(v) for v in pos], orient,
                    physicsClientId=self.client)
        # 固定步长模拟（累积真实 dt，pybullet 内部 240Hz 子步）
        self._accum += max(0.0, dt)
        guard = 0
        while self._accum >= _SUB_STEP and guard < 40:
            pb.stepSimulation(physicsClientId=self.client)
            self._accum -= _SUB_STEP
            guard += 1
        # 回写世界 Transform（根级无父物体；父物体由其父驱动）
        for uuid, bodyId in list(self.goToBody.items()):
            go = self.bodies.get(bodyId)
            if go is None or not go.active or go.parent is not None:
                continue
            rb = go.getComponent(Rigidbody)
            if rb is not None and rb.isKinematic:
                continue  # 运动学由 Transform 驱动，不回写
            pos, orient = pb.getBasePositionAndOrientation(bodyId,
                                                           physicsClientId=self.client)
            go.transform.position = np.asarray(pos, dtype=float)
            eul = pb.getEulerFromQuaternion(orient, physicsClientId=self.client)
            go.transform.rotation = np.asarray(eul, dtype=float)

    # ---- 脚本 API 支撑 ----
    def setVelocity(self, go, vx, vy, vz):
        bodyId = self.goToBody.get(getattr(go, "uuid", ""))
        if bodyId is None:
            return False
        try:
            pb.resetBaseVelocity(bodyId, [float(vx), float(vy), float(vz)],
                                 physicsClientId=self.client)
            return True
        except Exception:
            return False

    def getVelocity(self, go):
        bodyId = self.goToBody.get(getattr(go, "uuid", ""))
        if bodyId is None:
            return (0.0, 0.0, 0.0)
        try:
            lin, _ang = pb.getBaseVelocity(bodyId, physicsClientId=self.client)
            return tuple(float(v) for v in lin)
        except Exception:
            return (0.0, 0.0, 0.0)

    def applyForce(self, go, fx, fy, fz):
        bodyId = self.goToBody.get(getattr(go, "uuid", ""))
        if bodyId is None:
            return False
        try:
            pb.applyExternalForce(bodyId, -1, [float(fx), float(fy), float(fz)],
                                  [0.0, 0.0, 0.0], pb.WORLD_FRAME,
                                  physicsClientId=self.client)
            return True
        except Exception:
            return False

    def getVelocityOf(self, go):
        return self.getVelocity(go)


# 全局单例（编辑器播放期间只有一个物理世界）
_world = PhysicsWorld()


def getPhysicsWorld():
    """获取全局物理世界实例（脚本 API 用）。"""
    return _world
