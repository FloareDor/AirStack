"""Planner-independent PhysX contact and nominal spherical clearance oracle."""
import math
from pxr import Gf, PhysxSchema, Usd, UsdGeom, UsdPhysics
import omni.physx
from isaacsim.sensors.physics import _sensor

from clearance_search import solve


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
        # Subtract what the vehicle actually spans, not an assumed 0.25m. With
        # the nominal radius a genuine contact read as about +0.098, so most
        # collisions reported a positive margin. The measured hull is the
        # farthest extent, so this is the conservative end of an anisotropic
        # range: a head-on body contact happens nearer 0.25m and will now read
        # negative before it touches. That direction is the safe one for a
        # margin. A measurement outside a plausible band is not trusted, since
        # a stray bound on the drone subtree would silently wreck the metric.
        self.envelope=self.radius;self.envelope_source='nominal'
        if isinstance(self.hull_radius,float) and .1<=self.hull_radius<=1.:
            self.envelope=self.hull_radius;self.envelope_source='measured_hull'
        # Subtracting one scalar in every direction is wrong in both signs: the
        # nominal 0.25m was smaller than the vehicle, so contacts read positive;
        # the measured 0.3482m is the box DIAGONAL, so a flight that passed
        # 0.288m from a wall and never touched it read -0.060. Grow the drone's
        # actual oriented box instead and bracket the dilation that first
        # touches, which is a real distance along the direction of approach.
        self.box=self.measure_box(stage)
        self.clearance_basis='sphere_minus_envelope'
        if self.box and self.box_query_works():self.clearance_basis='oriented_box'
        half,centre=self.box if self.box else (None,None)
        self.status={'available':True,'armed':False,'collision':None,'bodies':self.bodies,
            'nominal_envelope_m':self.radius,'measured_hull_radius_m':self.hull_radius,
            'clearance_envelope_m':self.envelope,'clearance_envelope_source':self.envelope_source,
            'clearance_basis':self.clearance_basis,'box_half_extents_m':half,'box_centre_offset_m':centre}

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

    def measure_box(self,stage):
        """Half-extents and centre of the drone's colliders in the root's frame.

        Measurement only, like measure_hull: any problem returns None and the
        oracle falls back to the scalar envelope rather than failing to start,
        because this same object decides whether a flight collided.
        """
        try:return self._measure_box(stage)
        except Exception:return None

    def _measure_box(self,stage):
        root=stage.GetPrimAtPath(self.root)
        if not root or not root.IsValid():return None
        cache=UsdGeom.BBoxCache(Usd.TimeCode.Default(),['default','render','proxy','guide'])
        lo=[math.inf]*3;hi=[-math.inf]*3;seen=False
        for prim in Usd.PrimRange(root):
            if not prim.IsA(UsdGeom.Mesh) and not prim.IsA(UsdGeom.Gprim):continue
            if not prim.HasAPI(UsdPhysics.CollisionAPI):continue
            # Bound in the root's own frame. Taking a world bound and rotating
            # it back would re-wrap a rotated box and inflate the extents.
            try:box=cache.ComputeRelativeBound(prim,root).ComputeAlignedRange()
            except Exception:continue
            if box.IsEmpty():continue
            seen=True
            for a in range(3):
                lo[a]=min(lo[a],float(box.GetMin()[a]));hi[a]=max(hi[a],float(box.GetMax()[a]))
        if not seen:return None
        half=[(hi[a]-lo[a])/2 for a in range(3)];centre=[(hi[a]+lo[a])/2 for a in range(3)]
        # A stray bound on the drone subtree would silently wreck the metric,
        # so refuse anything outside a plausible vehicle size.
        if not all(.01<=h<=1. for h in half):return None
        return half,centre

    def box_query_works(self):
        """Does this build expose overlap_box, and does it accept our types?

        Probed once at startup with a box far from anything, so a binding that
        is missing or differently shaped degrades to the scalar envelope here
        rather than raising on every sample mid-flight.
        """
        if not hasattr(self.query,'overlap_box'):return False
        try:self.overlap_box_at((.01,.01,.01),(0.,0.,1e6),(0.,0.,0.,1.));return True
        except Exception:return False

    def overlap_box_at(self,half,centre,rot):
        found=[]
        def hit(result):
            path=str(result.collision)
            if self.external(path):found.append(path);return False
            return True
        self.query.overlap_box(tuple(map(float,half)),tuple(map(float,centre)),
                               tuple(map(float,rot)),hit,False)
        return bool(found)

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

    def clearance(self,point,orientation=None,maximum=5.):
        if self.clearance_basis=='oriented_box' and orientation is not None:
            try:return self.clearance_box(point,orientation,maximum)
            except Exception:
                # Do not keep advertising a basis we have stopped using.
                self.clearance_basis='sphere_minus_envelope_after_box_failure'
                self.status['clearance_basis']=self.clearance_basis
        return self.clearance_sphere(point,maximum)

    def clearance_box(self,point,orientation,maximum=5.):
        """Distance from the vehicle's own box to the nearest surface.

        Grows the box the drone actually occupies, in its current attitude,
        until it touches. Zero is contact in the direction that matters rather
        than contact with a sphere the vehicle was never shaped like.
        """
        half,centre=self.box
        qx,qy,qz,qw=(float(v) for v in orientation)
        turn=Gf.Rotation();turn.SetQuat(Gf.Quatd(qw,Gf.Vec3d(qx,qy,qz)))
        world=Gf.Vec3d(*map(float,point))+turn.TransformDir(Gf.Vec3d(*centre))
        def hits(t):
            return self.overlap_box_at((half[0]+t,half[1]+t,half[2]+t),tuple(world),(qx,qy,qz,qw))
        # Below its smallest half-extent the shrunken box is degenerate, so that
        # is as deep a penetration as this can resolve.
        return solve(hits,-min(half)*.99,maximum)

    def clearance_sphere(self,point,maximum=5.):
        # Query the actual triangle colliders, not just three box bounds.
        # Retained for builds without overlap_box. It subtracts one scalar in
        # every direction, so it reads penetration on flights that never
        # touched anything; prefer clearance_box.
        if not self.overlap(point,maximum):return maximum-self.envelope,True
        lo,hi=0.,maximum
        for _ in range(13):
            mid=(lo+hi)/2
            if self.overlap(point,mid):hi=mid
            else:lo=mid
        return lo-self.envelope,False

    def update(self,t,position,orientation=None):
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
            try:contact_clearance,contact_censored=self.clearance(position,orientation)
            except Exception:contact_clearance,contact_censored=None,None
            self.clearance_at_contact=contact_clearance
            self.collision={'sim_time':t,'objects':sorted(contacts),
                'position':list(map(float,position)),'drone_position':list(map(float,position)),
                'clearance_at_contact_m':contact_clearance,
                # Surface distance is the clearance plus whatever was taken off
                # it. Nothing is taken off the box basis, where the clearance is
                # already the hull-to-surface distance.
                'surface_distance_at_contact_m':None if contact_clearance is None
                    else (contact_clearance if self.clearance_basis=='oriented_box'
                          else contact_clearance+self.envelope),
                'clearance_basis':self.clearance_basis,
                'clearance_censored_at_contact':contact_censored,
                'measured_hull_radius_m':self.hull_radius,
                'clearance_envelope_m':self.envelope,'clearance_envelope_source':self.envelope_source}
        self.status.update(armed=self.armed,contacts=sorted(contacts),collision=self.collision,sim_time=t)
        if t-self.last_clearance>=.1:
            distance,censored=self.clearance(position,orientation)
            box=self.clearance_basis=='oriented_box'
            self.status.update(clearance_m=distance,clearance_censored=censored,
                surface_distance_m=distance if box else distance+self.envelope,
                clearance_method=('PhysX overlap of the vehicle fitted oriented collider box, grown until it '
                    'touches; the value is hull-to-surface distance along the direction of closest approach, '
                    'so zero is contact and negative is penetration.') if box else
                    (f'PhysX mesh distance minus a {self.envelope:.4f}m vehicle envelope ({self.envelope_source}); '
                     'one scalar is subtracted in every direction, so a pass closer than the hull diagonal reads '
                     'negative without contact. Fallback basis; prefer oriented_box.'),
                clearance_sim_time=t)
            self.last_clearance=t
        return self.status
