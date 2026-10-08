"""Planner-independent PhysX contact and nominal spherical clearance oracle."""
import math
from pxr import Gf, PhysxSchema, Usd, UsdGeom, UsdPhysics
import omni.physx
from isaacsim.sensors.physics import _sensor


class SceneOracle:
    def __init__(self, stage, root='/World/base_link', radius=.25):
        self.root=root;self.radius=radius;self.bodies=[]
        for prim in Usd.PrimRange(stage.GetPrimAtPath(root)):
            if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                PhysxSchema.PhysxContactReportAPI.Apply(prim).CreateThresholdAttr(0.)
                self.bodies.append(str(prim.GetPath()))
        if not self.bodies:raise RuntimeError('no drone rigid bodies for contact reporting')
        self.sensor=_sensor.acquire_contact_sensor_interface()
        self.query=omni.physx.get_physx_scene_query_interface()
        self.armed=False;self.collision=None;self.last_clearance=-1.
        self.clearance_at_contact=None
        # The 0.25m sphere is a reporting convention, not the vehicle. Measure
        # what the drone's colliders actually span so a reported margin can be
        # compared against something real: on 2026-10-08 twelve of fourteen
        # collisions reported a positive clearance because this was assumed.
        self.hull_radius=self.measure_hull(stage)
        self.status={'available':True,'armed':False,'collision':None,'bodies':self.bodies,
            'nominal_envelope_m':self.radius,'measured_hull_radius_m':self.hull_radius}

    def measure_hull(self,stage):
        """Farthest extent of the drone's own colliders from its root origin.

        Measurement only. It must never prevent the oracle from starting, because
        the oracle is also what decides whether a flight collided: a failure here
        would turn every flight into an infrastructure error. Any problem returns
        None and the status simply carries no measured radius.
        """
        try:return self._measure_hull(stage)
        except Exception:return None

    def _measure_hull(self,stage):
        root=stage.GetPrimAtPath(self.root)
        if not root or not root.IsValid():return None
        cache=UsdGeom.BBoxCache(Usd.TimeCode.Default(),['default','render','proxy','guide'])
        try:origin=UsdGeom.Xformable(root).ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()
        except Exception:return None
        far=0.;seen=False
        for prim in Usd.PrimRange(root):
            if not prim.IsA(UsdGeom.Mesh) and not prim.IsA(UsdGeom.Gprim):continue
            if not prim.HasAPI(UsdPhysics.CollisionAPI):continue
            try:box=cache.ComputeWorldBound(prim).ComputeAlignedRange()
            except Exception:continue
            if box.IsEmpty():continue
            seen=True
            for i in range(8):
                corner=Gf.Vec3d(box.GetMin()[0] if i&1 else box.GetMax()[0],
                                box.GetMin()[1] if i&2 else box.GetMax()[1],
                                box.GetMin()[2] if i&4 else box.GetMax()[2])
                far=max(far,float((corner-origin).GetLength()))
        return far if seen else None

    def external(self,path):
        return bool(path) and path!=self.root and not path.startswith(self.root+'/')

    def overlap(self,point,radius):
        found=[]
        def hit(result):
            path=str(result.collision)
            if self.external(path):found.append(path);return False
            return True
        self.query.overlap_sphere(float(radius),tuple(map(float,point)),hit,False)
        return bool(found)

    def clearance(self,point,maximum=5.):
        # Query the actual triangle colliders, not just three box bounds. The
        # sphere is a nominal vehicle envelope, not the exact collision hull.
        if not self.overlap(point,maximum):return maximum-self.radius,True
        lo,hi=0.,maximum
        for _ in range(13):
            mid=(lo+hi)/2
            if self.overlap(point,mid):hi=mid
            else:lo=mid
        return lo-self.radius,False

    def update(self,t,position):
        if position[2]>.3:self.armed=True
        contacts=set()
        for body in self.bodies:
            for contact in self.sensor.get_rigid_body_raw_data(body):
                values=list(contact)
                names=[self.sensor.decode_body_name(values[i]) for i in (2,3)]
                contacts.update(p for p in names if self.external(p))
        if self.armed and contacts and self.collision is None:
            # Measure the margin at the instant of contact. A flight that
            # collided while reporting +0.12 must not be mistaken for a flight
            # that stayed 0.12m clear, which the minimum alone cannot show.
            # 'position' is the DRONE's position, not the obstacle's.
            try:contact_clearance,contact_censored=self.clearance(position)
            except Exception:contact_clearance,contact_censored=None,None
            self.clearance_at_contact=contact_clearance
            self.collision={'sim_time':t,'objects':sorted(contacts),
                'position':list(map(float,position)),'drone_position':list(map(float,position)),
                'clearance_at_contact_m':contact_clearance,
                'surface_distance_at_contact_m':None if contact_clearance is None else contact_clearance+self.radius,
                'clearance_censored_at_contact':contact_censored,
                'measured_hull_radius_m':self.hull_radius}
        self.status.update(armed=self.armed,contacts=sorted(contacts),collision=self.collision,sim_time=t)
        if t-self.last_clearance>=.1:
            distance,censored=self.clearance(position)
            self.status.update(clearance_m=distance,clearance_censored=censored,
                surface_distance_m=distance+self.radius,
                clearance_method='PhysX mesh distance minus nominal 0.25m sphere (not exact hull); '
                    'a positive value is NOT a safety margin and sphere overlap misses thin foliage',
                clearance_sim_time=t)
            self.last_clearance=t
        return self.status
