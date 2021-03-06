"""
Pose Library mockup.

Non-functional, just creates some nice buttons and panels to look at and wish
they were real.
"""

bl_info = {
    "name": "Pose Library Mockup",
    "author": "Sybren A. Stüvel",
    "version": (1, 0),
    "blender": (2, 93, 0),
    "location": "3D View Numerical Panel > Animation",
    "category": "Animation",
}

import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union, cast

import bpy
from mathutils import Matrix
from bpy.props import BoolProperty, EnumProperty, StringProperty, CollectionProperty
from bpy.types import Action, Context, FCurve, Keyframe, Menu, Operator, Panel, UIList

from bpy_extras import asset_utils


def create_poselib_action(
    context: Context,
    src_action: Action,
    src_frame_nr: float,
    bone_names: Set[str],
    pose_name: str,
) -> Action:
    """Create a single-frame Action containing only the given bones."""

    dst_action = bpy.data.actions.new(pose_name)
    dst_action.id_root = src_action.id_root

    copy_fcurves(dst_action, src_action, src_frame_nr, bone_names)

    asset_mark_ctx = {
        **context.copy(),
        "id": dst_action,
    }
    bpy.ops.asset.mark(asset_mark_ctx)
    # TODO(Sybren): Add Asset metadata.

    return dst_action


def copy_fcurves(
    dst_action: Action,
    src_action: Action,
    src_frame_nr: float,
    bone_names: Set[str],
) -> None:
    pose_bone_re = re.compile(r'pose.bones\["([^"]+)"\]')
    for fcurve in src_action.fcurves:
        match = pose_bone_re.match(fcurve.data_path)
        if not match:
            continue

        bone_name = match.group(1)
        if bone_name not in bone_names:
            continue

        # Check if there is a keyframe on this frame.
        keyframe = find_keyframe(fcurve, src_frame_nr)
        if keyframe is None:
            continue
        # Create an FCurve and copy some properties.
        src_group_name = fcurve.group.name if fcurve.group else ""
        dst_fcurve = dst_action.fcurves.new(
            fcurve.data_path, index=fcurve.array_index, action_group=src_group_name
        )
        for propname in {"auto_smoothing", "color", "color_mode", "extrapolation"}:
            setattr(dst_fcurve, propname, getattr(fcurve, propname))

        # Insert a single keyframe and copy some properties. The keyframe is
        # eventually stored at frame=1 in the destination datablock. First
        # it's placed at the original frame, though, so that the handles can
        # be copied as-is. Later the `co_ui` attribute is used to move the
        # keyframe and the handles in one go.
        dst_keyframe = dst_fcurve.keyframe_points.insert(
            keyframe.co.x, keyframe.co.y, keyframe_type=keyframe.type
        )

        for propname in {
            "amplitude",
            "back",
            "easing",
            "handle_left",
            "handle_left_type",
            "handle_right",
            "handle_right_type",
            "interpolation",
            "period",
        }:
            setattr(dst_keyframe, propname, getattr(keyframe, propname))
        dst_keyframe.co_ui.x = 1.0  # This also moves the handles.
        dst_fcurve.update()


def find_keyframe(fcurve: FCurve, frame: float) -> Optional[Keyframe]:
    # Binary search adapted from https://pythonguides.com/python-binary-search/
    keyframes = fcurve.keyframe_points
    low = 0
    high = len(keyframes) - 1
    mid = 0

    # Accept any keyframe that's within 'epsilon' of the requested frame.
    # This should account for rounding errors and the likes.
    epsilon = 1e-4
    frame_lowerbound = frame - epsilon
    frame_upperbound = frame + epsilon
    while low <= high:
        mid = (high + low) // 2
        keyframe = keyframes[mid]
        if keyframe.co.x < frame_lowerbound:
            low = mid + 1
        elif keyframe.co.x > frame_upperbound:
            high = mid - 1
        else:
            return keyframe
    return None


class ANIM_OT_dummy(Operator):
    bl_idname = "anim.dummy"
    bl_label = "Dummy Operator"
    bl_options = {"REGISTER"}

    def execute(self, context: Context) -> Set[str]:
        return {"CANCELLED"}


class PoseAssetCreator:
    @classmethod
    def poll(cls, context: Context) -> bool:
        return bool(
            # There must be an object.
            context.object
            # It must be in pose mode with selected bones.
            and context.object.mode == "POSE"
            and context.object.pose
            and context.selected_pose_bones_from_active_object
            # There must be animation data to copy into the new Action.
            and context.object.animation_data
            and context.object.animation_data.action
        )


class ANIM_OT_create_pose_asset(PoseAssetCreator, Operator):
    bl_idname = "anim.create_pose_asset"
    bl_label = "Create Pose Asset"
    bl_options = {"REGISTER", "UNDO"}

    pose_name: StringProperty(name="Pose Name")  # type: ignore
    # TODO(Sybren): allow setting tags here.

    def execute(self, context: Context) -> Set[str]:
        src_action = context.object.animation_data.action

        bones = context.selected_pose_bones_from_active_object
        bone_names = {bone.name for bone in bones}

        create_poselib_action(
            context, src_action, context.scene.frame_current, bone_names, self.pose_name
        )
        return {"FINISHED"}

    def invoke(self, context: Context, _event: Any) -> Set[str]:
        wm = context.window_manager
        result = wm.invoke_props_dialog(self)
        return cast(Set[str], result)


class ANIM_OT_kick_to_own_file(PoseAssetCreator, Operator):
    bl_idname = "anim.kick_to_own_file"
    bl_label = "Store as one-frame Action"
    bl_options = {"REGISTER"}

    def execute(self, context: Context) -> Set[str]:
        src_action = context.object.animation_data.action

        bones = context.selected_pose_bones_from_active_object
        bone_names = {bone.name for bone in bones}

        dst_action = create_poselib_action(
            context,
            src_action,
            context.scene.frame_current,
            bone_names,
            "RENAME ME",
        )

        self.save_datablock(dst_action)
        bpy.data.actions.remove(dst_action)
        return {"FINISHED"}

    def save_datablock(self, action: Action) -> None:
        bpy.data.libraries.write(
            "my_secret_pose.blend",
            datablocks={action},
            path_remap="NONE",
            fake_user=True,
            compress=True,  # Single-datablock blend file, likely little need to diff.
        )


class VIEW3D_PT_pose_library(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Animation"
    bl_label = "Pose Library"

    def draw(self, context: Context) -> None:
        layout = self.layout

        col = layout.column(align=True)
        col.operator("anim.kick_to_own_file", text="Store As New Pose", icon="FILE_NEW")
        row = col.row(align=True)
        row.enabled = False
        row.operator("anim.dummy", text="Update Selected", icon="FILE_TICK")


class ASSETBROWSER_PT_pose_library_npanel(asset_utils.AssetBrowserPanel, Panel):
    bl_region_type = "TOOL_PROPS"
    bl_label = "Pose Library"

    def draw(self, context: Context) -> None:
        layout = self.layout

        # col = layout.column(align=True)
        # col.label(text="Storage")
        # col.operator("anim.dummy", text="Store As New Pose", icon="FILE_NEW")
        # col.operator("anim.dummy", text="Update Selected", icon="FILE_TICK")

        col = layout.column()
        # col.label(text="Application")
        col.prop(context.window_manager, "poselib_apply_flipped")
        row = col.row(align=True)
        if False:  # if selected pose is animation
            row.prop_enum(context.window_manager, "poselib_merge_choices", "INSERT")
        row.prop_enum(context.window_manager, "poselib_merge_choices", "REPLACE")
        row.prop_enum(context.window_manager, "poselib_merge_choices", "BLEND")

        row = col.row(align=True)
        row.operator("anim.dummy", text="Apply Pose")


class DOPESHEET_PT_asset_panel(Panel):
    bl_space_type = "DOPESHEET_EDITOR"
    bl_region_type = "UI"
    bl_label = "Pose Library"

    def draw(self, context: Context) -> None:
        layout = self.layout
        layout.operator("anim.create_pose_asset")


class ASSETBROWSER_PT_pose_library_tools(asset_utils.AssetBrowserPanel, Panel):
    bl_region_type = "TOOLS"
    bl_label = "Tags"

    def draw(self, context: Context) -> None:
        layout = self.layout

        col = layout.grid_flow(row_major=True, align=True, columns=2)
        col.operator("anim.dummy", text="★", depress=True)
        col.operator("anim.dummy", text="Front")
        col.operator("anim.dummy", text="Happy")
        col.operator("anim.dummy", text="Side")

        layout.label(text="Char:")
        col = layout.grid_flow(row_major=True, align=True, columns=2)
        col.operator("anim.dummy", text="Ellie")
        col.operator("anim.dummy", text="Rex")
        col.operator("anim.dummy", text="Spring", depress=True)
        col.operator("anim.dummy", text="Victoria")

        layout.label(text="Part:")
        col = layout.grid_flow(row_major=True, align=True, columns=2)
        col.operator("anim.dummy", text="Face", depress=True)
        col.operator("anim.dummy", text="Foot")
        col.operator("anim.dummy", text="Hand", depress=True)


classes = (
    ANIM_OT_create_pose_asset,
    ANIM_OT_dummy,
    ANIM_OT_kick_to_own_file,
    ASSETBROWSER_PT_pose_library_npanel,
    ASSETBROWSER_PT_pose_library_tools,
    DOPESHEET_PT_asset_panel,
    VIEW3D_PT_pose_library,
)

_register, _unregister = bpy.utils.register_classes_factory(classes)


def register():
    bpy.types.WindowManager.poselib_apply_flipped = BoolProperty(
        name="Apply Flipped",
        default=True,
    )
    bpy.types.WindowManager.poselib_merge_choices = EnumProperty(
        name="Animation",
        items=[
            ("REPLACE", "Replace", "Overwrite existing keyframes"),
            (
                "INSERT",
                "Insert",
                "Insert the animation segment, pushing existing keyframes down the timeline",
            ),
            ("BLEND", "Blend", "Blend with existing pose"),
        ],
        default="BLEND",
    )
    _register()


def unregister():
    _unregister()
    try:
        del bpy.types.WindowManager.poselib_apply_flipped
    except AttributeError:
        pass
    try:
        del bpy.types.WindowManager.poselib_merge_choices
    except AttributeError:
        pass
